# GPMPE: AWS Migration Plan

## 1. Overview
This document outlines the strategy for migrating the GPMPE platform to Amazon Web Services (AWS) while maintaining a **dual-build structure**. The goal is to ensure the application can be run locally using the existing SQLite/Filesystem architecture or deployed to AWS using Amazon RDS and persistent cloud storage, using the same codebase.

---

## 2. Architecture Comparison

| Feature | Local Development (Current) | AWS Production (Target) |
| :--- | :--- | :--- |
| **Database** | SQLite (File-based) | Amazon RDS (PostgreSQL/MySQL) |
| **Storage** | Local Disk (`pathlib`) | Amazon EFS (Elastic File System) |
| **Configuration** | `.config` file | AWS Secrets Manager / Parameter Store |
| **Compute** | Local Process / Docker | AWS Fargate (ECS) or AWS Lambda |
| **Data Sync** | Direct Manual Sync | Automated Git-to-EFS Worker |
| **Authentication** | None (Single User) | Amazon Cognito (RBAC) |

---

## 3. Phase 1: Database Abstraction (SQLAlchemy)
The current implementation is tightly coupled to the `sqlite3` library. We will refactor the backend to use **SQLAlchemy** as an ORM/Abstraction layer.

- **Task 1.1**: Define SQLAlchemy models mirroring the current schema.
- **Task 1.2**: Update `backend/app/db.py` to support dynamic engine creation based on a `DATABASE_URL` environment variable.
- **Task 1.3**: Abstract SQLite-specific features (like `PRAGMA`) into dialect-neutral migrations (e.g., using Alembic).
- **Outcome**: The app automatically uses SQLite if a local path is provided, or RDS if a networked connection string is provided.

### Current Phase 1 Status

- SQLAlchemy models and dynamic engine creation are in place.
- Several FastAPI endpoints now use SQLAlchemy sessions.
- SQLAlchemy-owned route handlers now use SQLAlchemy-backed YAML export helpers for campaign write-back instead of reopening `connect_database()`.
- The render API now builds PDF context and registers generated artifacts through the SQLAlchemy session path. The legacy renderer entry point remains available for local SQLite callers and direct tests.
- Non-SQLite/RDS startup no longer opens the legacy SQLite connection. If the database has data and `DATA_DIR` is empty, startup can export database state to YAML through SQLAlchemy. If YAML data is present and the database is empty, startup can import YAML into the database through SQLAlchemy. If both sides have data, startup can compare database and YAML state through SQLAlchemy and report reconciliation details.
- Whole-database YAML export now has a SQLAlchemy-backed implementation.
- YAML import/sync now has a SQLAlchemy-backed implementation, and the manual data sync and git-pull sync paths use it in RDS mode.
- Database-to-YAML comparison now has a SQLAlchemy-backed implementation for startup reconciliation in RDS mode.
- Campaign clone/import flows now have a SQLAlchemy-backed implementation, and the campaign clone API plus chat clone command use it.
- Read-only chatbot context/query commands now use SQLAlchemy session reads.
- Chat-driven campaign mutations now use a SQLAlchemy-backed mutation engine in the FastAPI chat route.
- LLM prompt-context building and LLM action dispatch now have SQLAlchemy-backed implementations in the FastAPI chat route.
- Legacy raw SQLite helper entry points remain for local/direct tests, but the primary FastAPI runtime paths no longer depend on them for RDS mode.
- `connect_database()` is intentionally guarded so it only runs in SQLite/local mode. If `DATABASE_URL` points to RDS, remaining legacy call paths fail loudly instead of silently writing to a separate local SQLite database.
- Next Phase 1 work should verify full RDS runtime parity and identify any remaining direct helper callers that need service-level wrappers before moving into backend modularization.

---

## 4. Phase 1.5: Backend Modularization

`backend/app/main.py` is currently over 2,000 lines and combines API route definitions, business logic, persistence orchestration, YAML synchronization, chat handling, rendering orchestration, data-manager snapshots, and artifact delivery. This makes the AWS migration harder to reason about and increases the risk of regressions.

This refactor should happen after the current database migration slice is stable, unless `main.py` complexity becomes the primary blocker to finishing Phase 1. The goal is to move behavior into focused modules without changing API contracts.

- **Current Status**:
    - Database session dependency and entity lookup guards have moved into `backend/app/dependencies.py`.
    - Request ID middleware has moved into `backend/app/middleware.py`.
    - FastAPI request/response schemas have moved into `backend/app/schemas.py`.
    - Campaign YAML persistence helpers have moved into `backend/app/services/yaml_persistence.py`.
    - Artifact save, render, list, download, and view endpoints have moved into `backend/app/routes/artifacts.py`.
    - Business and campaign CRUD/clone endpoints have moved into `backend/app/routes/business_campaigns.py`.
    - Data-manager snapshot helpers have moved into `backend/app/services/data_manager.py`, with data-manager endpoints in `backend/app/routes/data_manager.py`.
    - Offer and asset endpoints have moved into `backend/app/routes/offers_assets.py`.
    - Template and template-binding endpoints have moved into `backend/app/routes/templates.py`.
    - API behavior is unchanged; route groups are now being split one domain at a time.
- **Task 1.5.1: Split routes by domain**:
    - Business and campaign endpoints are complete.
    - Move offer, asset, template, component, artifact, chat, startup, data-sync, and data-manager endpoints into focused route modules.
    - Artifact, business/campaign, data-manager, offer, asset, and template endpoints are complete; remaining route groups should continue in small slices with full test runs after each slice.
- **Task 1.5.2: Introduce service-layer boundaries**:
    - Create service modules for campaign persistence, YAML sync/write-back, rendering/artifact registration, chat mutation, and data-manager snapshots.
    - Keep route handlers thin: validation, dependency injection, service call, response mapping.
- **Task 1.5.3: Centralize database dependencies**:
    - Keep SQLAlchemy session creation and legacy SQLite/local guards in one database dependency module.
    - Remove ad hoc imports of `connect_database()` from route handlers as service modules are migrated.
- **Task 1.5.4: Preserve external behavior**:
    - Keep existing API paths and response shapes stable.
    - Run the full backend suite after each extracted slice.
- **Outcome**: The backend has clear route/service/persistence boundaries, making the remaining RDS migration, Cognito authorization, and AWS deployment work easier to maintain.

---

## 5. Phase 2: Storage & Filesystem Parity (Amazon EFS)
To satisfy the requirement of maintaining YAML files for version control without a traditional local filesystem in AWS, we will use **Amazon EFS**.

- **Task 2.1**: Provision an Amazon EFS volume.
- **Task 2.2**: Mount the EFS volume to the AWS Fargate tasks or Lambda functions at `/app/data` and `/app/output`.
- **Task 2.3**: Ensure the application code uses configurable environment variables for `DATA_DIR` and `OUTPUT_DIR` (already partially implemented).
- **Outcome**: The codebase remains identical, using standard Python `pathlib` operations, while the underlying storage is a durable, networked cloud filesystem.

---

## 6. Phase 3: Version Control & Data Synchronization
Since YAML files in the repository are the authoritative source, we must synchronize them with the EFS volume in AWS.

- **Task 3.1: Git-to-Cloud Sync**: Implement a "Git Sync" utility (running as a sidecar container or a Lambda hook).
    - **Inbound**: When changes are pushed to the main repository, the worker performs a `git pull` into the EFS volume.
    - **Trigger**: The application's existing `sync_data_directory` logic is triggered to reconcile the new YAML state into the RDS database.
- **Task 3.2: Cloud-to-Git Write-Back**:
    - When edits are made via Chat/GUI, the backend writes to YAML on EFS.
    - The Git worker detects changes and performs a `git commit` and `git push` back to the repository using a machine user account.
- **Outcome**: Customers continue to use Git/YAML as their source of truth, while the AWS deployment stays perfectly in sync.

---

## 7. Phase 4: CI/CD and Dual Build
- **Task 4.1**: Update `Dockerfile` to be environment-aware.
- **Task 4.2**: Implement a GitHub Action or AWS CodePipeline that:
    1. Runs the test suite using SQLite (Local mode).
    2. Builds and pushes the Docker image to Amazon ECR.
    3. Deploys to ECS/Fargate.
- **Task 4.3**: Environment variable toggle `RUN_MODE=local|aws` to control specific behaviors (e.g., whether to use local `.config` or AWS Secrets Manager).

---

## 8. Phase 5: User Authentication & Access Control
To secure the application in AWS and support multi-user workflows, we will implement a role-based access control (RBAC) system.

### 7.1 User Roles & Hierarchy
- **Primary Admin**: The user associated with the AWS root login (or mapped identity) by default.
    - **Permissions**: Can add/delete all user types (Admin and Regular). Full access to all business profiles and campaigns.
- **Admin User**:
    - **Permissions**: Can create/modify business profiles. Can add Regular users. Can grant Regular users access to specific business profiles.
    - **Constraints**: Cannot add or modify other Admin users.
- **Regular User**:
    - **Permissions**: Can add and modify campaigns under business profiles they have been granted access to.
    - **Constraints**: Cannot create or modify business profiles. Cannot manage users.

### 7.2 Implementation Tasks
- **Task 5.1: Identity Integration**:
    - **AWS Mode**: Use **Amazon Cognito** for user identity management. Map Cognito groups to the application roles.
    - **Local Mode**: Implement a lightweight JWT-based authentication system backed by the local database for development parity.
- **Task 5.2: Backend Authorization**:
    - Implement FastAPI dependencies to enforce role-based access on all sensitive endpoints (e.g., `POST /businesses`, `PATCH /businesses`).
    - Add user-to-business mapping tables in the database to manage campaign access for Regular users.
- **Task 5.3: Admin Management Portal**:
    - Develop a web-based administrative dashboard within the frontend application.
    - Features: User onboarding, role assignment, business profile permissions, and administrative audit logs.

---

## 9. Phase 6: Verification & Parity
- **Parity Test**: Run the full backend test suite against an RDS instance in a staging VPC.
- **Sync Test**: Verify that editing a campaign title via the AWS-hosted chatbot results in a new commit appearing in the GitHub repository.
- **Local Fallback**: Confirm that developers can still run `start.sh` on their laptops with zero AWS dependencies.
