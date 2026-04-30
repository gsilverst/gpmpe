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

---

## 3. Phase 1: Database Abstraction (SQLAlchemy)
The current implementation is tightly coupled to the `sqlite3` library. We will refactor the backend to use **SQLAlchemy** as an ORM/Abstraction layer.

- **Task 1.1**: Define SQLAlchemy models mirroring the current schema.
- **Task 1.2**: Update `backend/app/db.py` to support dynamic engine creation based on a `DATABASE_URL` environment variable.
- **Task 1.3**: Abstract SQLite-specific features (like `PRAGMA`) into dialect-neutral migrations (e.g., using Alembic).
- **Outcome**: The app automatically uses SQLite if a local path is provided, or RDS if a networked connection string is provided.

---

## 4. Phase 2: Storage & Filesystem Parity (Amazon EFS)
To satisfy the requirement of maintaining YAML files for version control without a traditional local filesystem in AWS, we will use **Amazon EFS**.

- **Task 2.1**: Provision an Amazon EFS volume.
- **Task 2.2**: Mount the EFS volume to the AWS Fargate tasks or Lambda functions at `/app/data` and `/app/output`.
- **Task 2.3**: Ensure the application code uses configurable environment variables for `DATA_DIR` and `OUTPUT_DIR` (already partially implemented).
- **Outcome**: The codebase remains identical, using standard Python `pathlib` operations, while the underlying storage is a durable, networked cloud filesystem.

---

## 5. Phase 3: Version Control & Data Synchronization
Since YAML files in the repository are the authoritative source, we must synchronize them with the EFS volume in AWS.

- **Task 3.1: Git-to-Cloud Sync**: Implement a "Git Sync" utility (running as a sidecar container or a Lambda hook).
    - **Inbound**: When changes are pushed to the main repository, the worker performs a `git pull` into the EFS volume.
    - **Trigger**: The application's existing `sync_data_directory` logic is triggered to reconcile the new YAML state into the RDS database.
- **Task 3.2: Cloud-to-Git Write-Back**:
    - When edits are made via Chat/GUI, the backend writes to YAML on EFS.
    - The Git worker detects changes and performs a `git commit` and `git push` back to the repository using a machine user account.
- **Outcome**: Customers continue to use Git/YAML as their source of truth, while the AWS deployment stays perfectly in sync.

---

## 4. Phase 4: CI/CD and Dual Build
- **Task 4.1**: Update `Dockerfile` to be environment-aware.
- **Task 4.2**: Implement a GitHub Action or AWS CodePipeline that:
    1. Runs the test suite using SQLite (Local mode).
    2. Builds and pushes the Docker image to Amazon ECR.
    3. Deploys to ECS/Fargate.
- **Task 4.3**: Environment variable toggle `RUN_MODE=local|aws` to control specific behaviors (e.g., whether to use local `.config` or AWS Secrets Manager).

---

## 6. Phase 5: Verification & Parity
- **Parity Test**: Run the full backend test suite against an RDS instance in a staging VPC.
- **Sync Test**: Verify that editing a campaign title via the AWS-hosted chatbot results in a new commit appearing in the GitHub repository.
- **Local Fallback**: Confirm that developers can still run `start.sh` on their laptops with zero AWS dependencies.
