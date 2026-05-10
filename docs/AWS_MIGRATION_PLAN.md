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
- RDS runtime parity has been audited after modularization. Remaining `connect_database()` usage in FastAPI routes is isolated to explicit SQLite/local branches in startup reconciliation and data sync operations.
- Phase 1 is ready to proceed into storage/filesystem parity work, with one recommended staging validation: run the backend suite and core render/sync smoke tests against an actual RDS instance.

---

## 4. Phase 1.5: Backend Modularization

`backend/app/main.py` previously exceeded 2,000 lines and combined API route definitions, business logic, persistence orchestration, YAML synchronization, chat handling, rendering orchestration, data-manager snapshots, and artifact delivery. That made the AWS migration harder to reason about and increased the risk of regressions.

This refactor has been completed without changing API contracts. `backend/app/main.py` is now focused on app setup, middleware, lifespan startup, and route registration.

- **Current Status**:
    - Phase 1.5 is complete.
    - Database session dependency and entity lookup guards have moved into `backend/app/dependencies.py`.
    - Request ID middleware has moved into `backend/app/middleware.py`.
    - FastAPI request/response schemas have moved into `backend/app/schemas.py`.
    - Campaign YAML persistence helpers have moved into `backend/app/services/yaml_persistence.py`.
    - Artifact save, render, list, download, and view endpoints have moved into `backend/app/routes/artifacts.py`.
    - Business and campaign CRUD/clone endpoints have moved into `backend/app/routes/business_campaigns.py`.
    - Data-manager snapshot helpers have moved into `backend/app/services/data_manager.py`, with data-manager endpoints in `backend/app/routes/data_manager.py`.
    - Offer and asset endpoints have moved into `backend/app/routes/offers_assets.py`.
    - Template and template-binding endpoints have moved into `backend/app/routes/templates.py`.
    - Component and component-item endpoints have moved into `backend/app/routes/components.py`.
    - Chat session and message endpoints have moved into `backend/app/routes/chat.py`.
    - Health, startup reconciliation, and data sync endpoints have moved into `backend/app/routes/ops.py`.
    - API behavior is unchanged; all planned route groups have been split into focused modules.
- **Task 1.5.1: Split routes by domain**:
    - Business and campaign endpoints are complete.
    - Artifact, business/campaign, chat, component, data-manager, data-sync, offer, asset, startup, and template endpoints are complete.
- **Task 1.5.2: Introduce service-layer boundaries**:
    - Service modules now cover shared YAML persistence and data-manager snapshots.
    - Additional service extraction can continue opportunistically, but it is no longer blocking the AWS migration.
- **Task 1.5.3: Centralize database dependencies**:
    - SQLAlchemy session creation and entity lookup helpers are centralized in `backend/app/dependencies.py`.
    - Remaining `connect_database()` usage is limited to SQLite/local compatibility branches.
- **Task 1.5.4: Preserve external behavior**:
    - Keep existing API paths and response shapes stable.
    - Run the full backend suite after each extracted slice.
- **Outcome**: The backend has clear route/service/persistence boundaries, making the remaining RDS migration, Cognito authorization, and AWS deployment work easier to maintain.

---

## 5. Phase 2: Storage & Filesystem Parity (Amazon EFS)
To satisfy the requirement of maintaining YAML files for version control without a traditional local filesystem in AWS, we will use **Amazon EFS**.

- **Current Status**:
    - `DATA_DIR`, `OUTPUT_DIR`, `DATABASE_PATH`, `DATABASE_URL`, test-path settings, Git settings, and OpenRouter settings can be supplied through environment variables, with `.config` still supported for local mode.
    - Docker Compose already maps `/app/data`, `/app/output`, and `/app/backend/data` to named volumes; those same paths can be backed by EFS in AWS.
    - YAML write-back and PDF rendering use atomic file replacement.
    - Campaign clone YAML updates now also use atomic file replacement, so chat/GUI clone flows are safer on EFS-backed storage.
    - `backend/tests/test_efs_storage_parity.py` provides a local EFS-style smoke test for env-configured paths, data sync, YAML mutation write-back, chat clone, and render output.
- **Task 2.1**: Provision an Amazon EFS volume.
- **Task 2.2**: Mount the EFS volume to the AWS Fargate tasks or Lambda functions at `/app/data` and `/app/output`.
- **Task 2.3**: Set `DATA_DIR=/app/data` and `OUTPUT_DIR=/app/output` in the AWS task/container environment.
- **Task 2.4**: Validate EFS permissions by running `backend/tests/test_efs_storage_parity.py` locally and repeating the same sync, campaign mutation, clone, and render flow against mounted EFS paths in AWS.
- **Outcome**: The codebase remains identical, using standard Python `pathlib` operations, while the underlying storage is a durable, networked cloud filesystem.

---

## 6. Phase 3: Version Control & Data Synchronization
Since YAML files in the deployment owner's configured business data repository are the authoritative source, we must synchronize them with the EFS volume in AWS. This business data repository is separate from the GPMPE application source repository and must not store its customer/business/campaign YAML in the upstream project repository.

- **Current Status**:
    - The application exposes `/data/pull` to pull from Git and then reconcile YAML into the active database.
    - `backend/scripts/git_sync_worker.sh` can run as a polling sidecar and call `/data/pull`.
    - Campaign saves can create Git commits when `COMMIT_ON_SAVE=true` and Git author/repository settings are configured.
    - Git push is now explicit and disabled by default through `GIT_PUSH_ENABLED=false`, so local and staging environments can commit without requiring outbound repository credentials.
    - Git pull/commit/push operations are guarded by an EFS-compatible `.gpmpe-git.lock` file with a configurable `GIT_LOCK_TIMEOUT_SECONDS` timeout.
- **Task 3.1: Git-to-Cloud Sync**: Deploy the Git sync worker as an ECS sidecar mounted to the same EFS data volume as the application.
    - Configure `GPMPE_API_URL`, `SYNC_INTERVAL_SECONDS`, `GIT_REPO_PATH`, `GIT_USER_NAME`, `GIT_USER_EMAIL`, `GIT_REMOTE`, `GIT_BRANCH`, and `GIT_LOCK_TIMEOUT_SECONDS` in the task environment.
    - Configure the remote repository outside the application source repo. The deployment administrator is responsible for selecting, creating, protecting, and granting runtime access to the business data repository.
    - Inbound flow: the worker calls `/data/pull`; the backend runs `git pull --rebase` for the configured remote/branch and reconciles changed YAML into RDS.
    - Add CloudWatch logs and alarms for pull failures, API reachability failures, and reconciliation conflicts.
- **Task 3.2: Cloud-to-Git Write-Back**:
    - When edits are made via Chat/GUI, the backend writes YAML on EFS and can commit those changed YAML files through the existing save endpoint.
    - Enable outbound repository pushes only after credentials are ready by setting `GIT_PUSH_ENABLED=true`.
    - Store AWS-mode Git credentials in AWS Secrets Manager or ECS task secrets, preferably using a GitHub App, deploy key, or narrowly scoped machine-user token.
    - Treat the configured Git identity as an application/service identity, not the signed-in end user's personal Git credentials.
    - Confirm the target branch strategy before enabling push in production. The initial default should be a protected integration branch rather than direct writes to `main`.
- **Task 3.2a: AWS Integration for Admin-Managed Git Credentials**:
    - Assume the application provides an administrator interface for managing global Git defaults and business-profile-specific Git settings in both local and AWS deployments.
    - Store business-profile repository name/URL, branch/ref, push policy, and credential reference as administrator-only business profile fields so each business can be backed by its own Git repository.
    - Prefer one administrator-managed service credential per business repository. Provide optional global/default Git credential settings only as a fallback for deployments that intentionally share credentials across businesses.
    - In AWS mode, map each administrator-managed credential reference to AWS Secrets Manager or ECS task secrets.
    - Do not store raw Git tokens or private keys in RDS. Store only secret references/metadata in application tables and keep secret material in AWS-managed secrets.
    - Do not use individual signed-in user credentials for Git repository authentication. Git operations should use the configured business or global service credential, while the signed-in user's email/user ID is recorded as object version metadata.
    - Validate that Primary Admin/Admin users can create/update/rotate global and business-profile Git credential settings through the application interface and that regular users cannot view or modify Git credentials.
    - Validate audit logging for Git credential changes, including the admin user, scope (`global` or business profile), repository/branch metadata, and rotation timestamp.
- **Task 3.2b: Administrator Business ZIP Import for Bootstrap**:
    - Add an administrator-only bootstrap/import path that operates on one business directory at a time, rather than the full `DATA_DIR`.
    - Support a ZIP package containing exactly one business root directory from a deployment-owned business data repository.
    - Support importing from a configured business-specific Git repository by checking out the selected branch/ref into temporary space, packaging the checked-out business directory as a ZIP, and passing it through the same preview/import validation as uploaded ZIP files.
    - Preserve the runtime EFS layout as one configured `DATA_DIR` with one child directory per business, even when each child business directory is sourced from a separate Git repository.
    - In AWS mode, allow the administrator to point to an S3 object URI or equivalent external object reference for the ZIP, with direct upload as a possible local/admin convenience.
    - Treat the S3 bucket as an import-package staging area only. It should store ZIP objects such as `merci.zip`, not a `data/` directory mirror, and it should not be presented as the runtime data store or source-of-truth business data repository.
    - Validate package structure, data schema version, path safety, and existing-business conflicts before writing anything to EFS or RDS.
    - Show a preview of the business profile, promotions, business-card designs, and conflict action before import confirmation.
    - After confirmation, extract the accepted business directory into the EFS-backed `DATA_DIR` and run business-scoped YAML-to-RDS synchronization.
    - Record each import in the audit log with actor, source type, business name, package checksum, result, and timestamp.
    - Current status: local/raw-ZIP and S3 URI backend preview/import endpoints exist. The AWS bucket, lifecycle rule, and ECS task-role read policy have been created for staging. The staging ECS image has been rebuilt/redeployed with this support, and a real S3-backed business import smoke test succeeded from preview through import, RDS sync, EFS write, API reads, and audit-log recording. The administrator UI flow remains pending.
- **Task 3.3: Sync Safety Controls**:
    - Validate the EFS-backed `.gpmpe-git.lock` behavior with the deployed ECS task count before scaling beyond one application task and one sync worker.
    - Keep commit scope restricted to configured YAML/data paths so generated PDFs, database files, and unrelated files are never pushed.
    - Define conflict behavior: surface a 409/error state, leave the repo in an inspectable state, and require admin intervention before retrying destructive resolution.
- **Task 3.4: Verification**:
    - Add GitStore tests with temporary repositories for commit-only, push-disabled, push-enabled failure, pull, and path-boundary behavior. **Complete.**
    - Add a local end-to-end sync flow test that mirrors the AWS path with a bare remote, an EFS-like cloned data repo, `/data/pull`, YAML-to-DB reconciliation, campaign save, and push back to the remote. **Complete.**
    - Run a staging sync test where a Git commit updates YAML, `/data/pull` imports it into RDS, a chatbot edit writes YAML on EFS, and a save operation pushes a new commit back to the configured branch.
- **Outcome**: Customers continue to use Git/YAML as their source of truth, while the AWS deployment stays perfectly in sync.

---

## 7. Phase 4: CI/CD and Dual Build
- **Task 4.1**: Update `Dockerfile` to be environment-aware.
- **Task 4.2**: Provide deployment scaffolding that a deployment owner can run from their own deployment repository, using GitHub Actions, AWS CodePipeline, or another CI/CD system to:
    1. Run the test suite using SQLite (Local mode).
    2. Build and push the Docker image to Amazon ECR.
    3. Deploy to ECS/Fargate.
- **Task 4.3**: Environment variable toggle `RUN_MODE=local|aws` to control specific behaviors (e.g., whether to use local `.config` or AWS Secrets Manager).
- **Current Status**:
    - `RUN_MODE=local|aws` is parsed by application config, defaults to `local`, and can be supplied through environment variables.
    - The Docker image has local defaults for `RUN_MODE`, `DATA_DIR`, `OUTPUT_DIR`, and `DATABASE_PATH`, while allowing AWS/ECS task definitions to override them with RDS/EFS settings.
    - The runtime image includes Git/OpenSSH tooling required by the sync worker.
    - GitHub Actions CI runs backend tests, builds the frontend export, and validates the Docker image build.
    - A manual GitHub Actions AWS deploy workflow scaffold now builds the image, pushes it to ECR, renders an ECS task definition, and deploys it to ECS/Fargate once account-specific values are supplied. Open-source deployment owners should copy or adapt this scaffold into their own deployment repository, such as a private `gpmpe-deployment` repo.
    - `aws/ecs-task-definition.template.json` provides the initial app-plus-git-sync-sidecar task shape, including EFS mounts for `/app/data` and `/app/output`.
    - `docs/AWS_DEPLOYMENT_RUNBOOK.md` documents the AWS values, GitHub variables/secrets, first deploy flow, staging validation, and rollback steps.
    - Actual ECR push and ECS deploy execution remain pending until AWS account identifiers, IAM roles, networking, RDS, EFS, deployment targets, and the deployment-owner CI/CD repository are available.

---

## 8. Open Design Consideration: Repository Ownership & Deployment Control

The AWS migration must clearly separate open-source application development, deployment ownership, and customer/business data ownership. The upstream GPMPE application repository can provide source code, examples, templates, and documentation, but it must not become the source of truth for any specific operator's AWS deployment or any customer's business/campaign YAML data.

- **Issue**: The current deploy workflow scaffold lives in the application source repository, which is useful as an example but can imply that the upstream project owns deployment state.
- **Issue**: The business data repository is administrator/customer controlled and may contain sensitive business profiles, marketing campaigns, and generated operational history. It must never be mixed into the application source repository.
- **Issue**: The correct OIDC trust target depends on who owns deployment automation. For open-source users, that should usually be their own deployment repository, not the upstream GPMPE repository.

### Resolution Tasks

- **Task 4.4: Define deployment ownership model**:
    - Decide whether the first hosted deployment is managed from a dedicated private deployment repository, such as `gpmpe-deployment`, or from another operator-controlled CI/CD system.
    - Document that deployment owners are responsible for environment-specific AWS identifiers, task definition overlays, secrets references, and release promotion controls.
- **Task 4.5: Convert deployment scaffold into portable template**:
    - Treat `.github/workflows/aws-deploy.yml` and `aws/ecs-task-definition.template.json` as example scaffolds.
    - Add documentation for copying/adapting those files into a deployment repository.
    - Avoid hard-coding upstream repository names in AWS trust policies or deploy instructions.
- **Task 4.6: Define business data repository contract**:
    - Specify the required repository layout for business profile and campaign YAML data.
    - Define how the application administrator interface configures the remote URL, branch, credentials reference, author identity, and push policy for the runtime Git sync worker in both local and AWS deployments.
    - Confirm that generated PDFs, local SQLite files, AWS credentials, deployment secrets, and application source files are excluded from business data commits.
- **Task 4.7: Define OIDC and runtime credential boundaries**:
    - Use OIDC only for deployment automation from the deployment-owner repository or CI/CD system.
    - Use separate runtime Git credentials for the business data repository, stored in AWS Secrets Manager or ECS task secrets.
    - Ensure deployment credentials cannot read or write customer campaign data unless an operator explicitly chooses to combine those concerns in their own private environment.
- **Outcome**: Open-source users can adopt GPMPE without coupling their AWS deployment or business data to the upstream project repository, while the first-party deployment remains reproducible and secure.

---

## 9. Phase 5: User Authentication & Access Control
To secure the application in AWS and support multi-user workflows, GPMPE should use AWS-native identity services first. The application should not manage passwords or become its own security provider. AWS Cognito should authenticate users and handle invite, password reset, MFA/session, and email-based login flows. The application database should store application data needed to apply business rules, such as role/profile mirrors, business access grants, audit logs, and version metadata.

### 9.1 User Roles & Hierarchy
- **Primary Admin**: The first administrator user or users explicitly designated during first-run setup after the AWS deployer brings the stack online.
    - **Permissions**: Can add/delete all user types (Admin and Regular). Full access to all business profiles and campaigns.
- **Admin User**:
    - **Permissions**: Can create/modify business profiles. Can add Regular users. Can grant Regular users access to specific business profiles.
    - **Constraints**: Cannot add or modify other Admin users.
- **Regular User**:
    - **Permissions**: Can add and modify campaigns under business profiles they have been granted access to, subject to the campaign-access policy for that business.
    - **Constraints**: Cannot create or modify business profiles. Cannot manage users.

Relevant test coverage:
- Existing: `backend/tests/test_auth.py::test_auth_status_disabled_by_default`
- Existing: `backend/tests/test_auth.py::test_auth_bootstrap_creates_primary_admin`
- Existing: `backend/tests/test_auth.py::test_admin_routes_require_authorized_user_when_auth_enabled`
- Existing: `backend/tests/test_auth.py::test_alb_oidc_identity_maps_to_app_user`
- Planned: tests for Primary Admin, Admin, and Regular User permission differences once role enforcement expands beyond admin-route guards.

### 9.1a Business And Campaign Access
- Keep the initial role model simple: Primary Admin, Admin, and Regular User. Additional roles or capabilities may be added later when user workspaces are implemented.
- Primary Admin/Admin users have access to every business profile and every campaign, and can grant or deny Regular User access at both the business and campaign level.
- Business access grants allow one Regular User to work across multiple businesses, while still keeping each business administratively independent.
- Each business profile should have a campaign-access policy setting. When `all_business_users_can_access_campaigns` is enabled, every Regular User with business access can view and edit campaigns under that business unless an admin later adds explicit restrictions.
- When `all_business_users_can_access_campaigns` is disabled, Regular Users can access campaigns they create by default. Access to other campaigns requires an explicit campaign grant.
- Campaign creators should be treated as campaign owners for access-management purposes. A campaign owner can invite other users with business access to view or collaborate on that campaign.
- Regular Users should be able to request access to a campaign. The request can be approved or denied by either the campaign owner or a Primary Admin/Admin user.
- Campaign-level access should support at least view and edit levels so a user can be invited to inspect a campaign without necessarily modifying it.
- Future workspace permissions should build on this model rather than replacing it: business access grants define broad eligibility, campaign grants define object-level access, and workspace grants can add organization and visibility rules later.

Relevant test coverage:
- Existing foundation: `backend/tests/test_auth.py::test_admin_routes_require_authorized_user_when_auth_enabled`
- Existing foundation: `backend/tests/test_auth.py::test_alb_oidc_identity_maps_to_app_user`
- Planned: tests for business-level grants allowing one Regular User to access multiple businesses.
- Planned: tests for `all_business_users_can_access_campaigns=true`.
- Planned: tests for `all_business_users_can_access_campaigns=false`.
- Planned: tests for campaign creator/owner default access.
- Planned: tests for campaign-level view/edit grants.
- Planned: tests for owner invitations and admin grant/deny changes.
- Planned: tests for access requests approved or denied by campaign owners and admins.

### 9.2 Implementation Tasks
- **Task 5.1: First-Run Admin Handoff**:
    - Add an explicit first-run setup page for AWS deployments so the deployer can hand off the running application to one or more Primary Admin users by email address.
    - The deployer's responsibility is to provision and deploy the AWS stack; the application's first-run setup should make the administrator handoff obvious instead of hiding it in environment variables or secret edits.
    - Protect first-run setup with a one-time bootstrap mechanism appropriate for AWS, such as a short-lived setup token or restricted deployer-only access path, then disable it after Primary Admin users are created.
    - Use the Primary Admin email address as the user ID and invite the user through Cognito.
    - Current status: the app exposes `/setup`, `/auth/status`, `/auth/bootstrap`, and `/auth/me`. The bootstrap flow creates the first app-level Primary Admin mirror record using a temporary `AUTH_BOOTSTRAP_TOKEN`; it does not store or manage passwords.
    - Relevant test coverage:
        - Existing: `backend/tests/test_auth.py::test_auth_status_disabled_by_default`
        - Existing: `backend/tests/test_auth.py::test_auth_bootstrap_creates_primary_admin`
        - Planned: test that bootstrap cannot run after the first Primary Admin exists.
        - Planned: test that bootstrap creates a Cognito invite once Cognito admin APIs are wired.
- **Task 5.2: Cognito Identity Integration**:
    - Use Amazon Cognito for AWS-mode user identity management, including email-based login, user invitations, password reset, MFA/session controls, and token validation.
    - Allow Primary Admin/Admin users to create or invite other Admin and Regular users from the application admin dashboard, with the app calling Cognito APIs to create users and send invite emails.
    - Decide whether broad role eligibility is represented in Cognito groups, app database records, or both. The preferred split is that Cognito handles authentication and optional coarse groups, while the app database stores application-specific roles, business access grants, and audit/version data.
    - Defer the local-mode authentication design until the AWS flow is concrete. Local mode may use a lighter-weight approximation later, but the AWS security model should lead the design.
    - Current status: the backend can read trusted AWS ALB/Cognito identity headers in `AUTH_MODE=alb_oidc` and map the authenticated email to an app user record. Full Cognito user pool, app client, hosted UI, ALB authentication action, and admin invite integration remain TODO.
    - Relevant test coverage:
        - Existing: `backend/tests/test_auth.py::test_alb_oidc_identity_maps_to_app_user`
        - Existing: `backend/tests/test_auth.py::test_admin_routes_require_authorized_user_when_auth_enabled`
        - Planned: tests for Cognito `AdminCreateUser` invite success/failure with mocked AWS responses.
        - Planned: tests for users authenticated by Cognito but missing app-user records.
        - Planned: tests for inactive app users.
- **Task 5.3: Backend Authorization**:
    - Implement FastAPI dependencies that validate Cognito-issued identity tokens and enforce role/business access on sensitive endpoints.
    - Add application data tables, or a logically separate authorization schema/database if desired, for user profile mirrors, app roles, business access grants, and audit metadata.
    - Treat those tables as application data that Cognito-backed authorization uses; do not store user passwords or raw authentication secrets in the application database.
    - Add campaign-access policy and grant tables for business defaults, campaign owners, per-campaign view/edit grants, and access-request workflow state.
    - Current status: app user and business-access grant tables exist. Admin settings, audit log, and business import endpoints are guarded by the new admin dependency whenever authentication is enabled; local/default deployments remain `AUTH_MODE=disabled`.
    - Relevant test coverage:
        - Existing: `backend/tests/test_auth.py::test_admin_routes_require_authorized_user_when_auth_enabled`
        - Existing: `backend/tests/test_admin_settings.py::test_admin_git_settings_save_metadata_secret_and_audit`
        - Existing: `backend/tests/test_admin_settings.py::test_admin_business_git_settings_save_secret_and_audit`
        - Existing: `backend/tests/test_business_import.py::test_admin_business_import_preview_and_import`
        - Existing: `backend/tests/test_business_import.py::test_admin_business_import_from_s3`
        - Planned: tests for business grant enforcement on business and campaign routes.
        - Planned: tests for campaign grant enforcement on view/edit/render/save routes.
        - Planned: tests for admin override behavior across all businesses and campaigns.
- **Task 5.4: Admin Management Portal**:
    - Develop a web-based administrative dashboard within the frontend application.
    - Features: Cognito-backed user onboarding/invites, role assignment, business profile permissions, campaign access grants/denials, campaign access-request review, global and business-specific Git credential references, and administrative audit logs.
    - Let administrators manage business-specific Git repository settings and credential references as part of the business profile, with optional global/default Git credentials for shared-credential deployments.
    - Store raw Git tokens, deploy keys, API keys, and database passwords only in AWS Secrets Manager/ECS task secrets. Store only references and non-sensitive metadata in RDS.
    - Relevant test coverage:
        - Existing: `backend/tests/test_admin_settings.py::test_admin_git_settings_default_to_config_values`
        - Existing: `backend/tests/test_admin_settings.py::test_admin_git_settings_save_metadata_secret_and_audit`
        - Existing: `backend/tests/test_admin_settings.py::test_admin_business_git_settings_inherit_global_until_overridden`
        - Existing: `backend/tests/test_admin_settings.py::test_admin_business_git_settings_save_secret_and_audit`
        - Existing: `frontend/tests/api.test.ts`
        - Existing: `frontend/tests/page.test.tsx`
        - Planned: frontend tests for the first-run setup page.
        - Planned: frontend/backend tests for admin user invites, business access grants, campaign grants, and access-request review.

### 9.3 AWS Multi-User Editing And Versioning
- AWS deployments should support multiple users editing the same campaign, business profile, or future business card by using per-user/per-object draft workspaces rather than direct concurrent mutation of canonical database rows.
- Draft workspaces should live on persistent AWS-backed storage, such as EFS or another shared working area, because Fargate task-local disk is ephemeral.
- The canonical database should represent the latest saved/imported version of each object. Draft edits become canonical only when the user saves the object, the application writes YAML, commits through the configured business Git credential, records version metadata, and syncs the saved object back into RDS.
- If another user saved a newer version of the same object after the current draft began, warn the user before saving. The warning should identify the other user in friendly terms and allow the current user to continue editing, compare previews where available, or save anyway as the next linear version.
- Regular users should see app-level versions by date/time, user, object name, and version number. Git commit IDs, branches, and repository mechanics should be hidden from normal campaign workflows.
- Version metadata should include the signed-in user's email/user ID, object type, object key/path, base version, resulting version, Git commit reference, timestamp, and summary. This metadata can be indexed in RDS for UI queries and written to the business repository in a business-level metadata ledger such as `<business>/.meta/versions.jsonl`.
- Business cards should follow the same object-level draft/save/version model as campaigns when that feature is implemented.

---

## 10. Phase 6: Verification & Parity
- **Parity Test**: Run the full backend test suite against an RDS instance in a staging VPC.
- **Sync Test**: Verify that editing a campaign title via the AWS-hosted chatbot results in a new commit appearing in the configured business data repository.
- **Local Fallback**: Confirm that developers can still run `start.sh` on their laptops with zero AWS dependencies.

---

## 11. Final Step: AWS Deployment User Guide

After the AWS deployment path is validated, add a detailed step-by-step AWS deployment section to the user guide. This should be written for deployment owners/administrators and should cover the complete setup flow, including:

- AWS account bootstrap, region selection, root MFA, administrator access, and budget alerts.
- ECR repository creation.
- CloudWatch log group creation and retention settings.
- Secrets Manager setup for database, LLM, Git author identity, and business data repository credentials.
- Cognito user pool setup, first-run Primary Admin handoff, admin user invites, regular user invites, and role/business-access administration.
- IAM roles for ECS task execution, ECS task runtime access, and deployment automation.
- Deployment repository ownership and OIDC trust setup for the deployment owner's CI/CD repository.
- RDS provisioning, backup policy, security groups, and `DATABASE_URL` secret setup.
- EFS provisioning, access points, mount targets, security groups, backup policy, and ECS mount configuration.
- ECS/Fargate cluster, task definition, service, networking, and load balancer setup.
- Business data repository setup, administrator configuration through the application admin page, and initial business-level bootstrap by importing one zipped business directory at a time, including the S3-backed ZIP import path for AWS deployments.
- Business-specific Git credential configuration, optional global/default Git credential configuration, and version metadata expectations for object-level saves.
- Multi-user editing behavior, including per-user draft workspaces, stale-base save warnings, and user-friendly version history/restore workflows.
- Git sync worker configuration and validation.
- First deployment from the deployment repository or selected CI/CD system.
- Health checks, startup reconciliation, campaign edit/save validation, PDF render validation, CloudWatch log review, rollback, and production promotion checklist.
- A detailed worked staging deployment example based on the successful first deployment, including concrete non-secret resource names, the chosen low-cost architecture, bootstrap/import flow, confirmed capabilities, known limitations, and troubleshooting lessons learned.

This section should distinguish clearly between the GPMPE application source repository, the deployment owner's infrastructure/deployment repository, and the administrator-managed business data repository.

---

## 12. Post-AWS Deployment Enhancements
These enhancements should be planned after the migration is complete and the application has been successfully deployed and validated in AWS.

- **Business-Profile-Specific Git Credentials**:
    - Add optional Git credential overrides at the business profile level after the global credential flow has been validated in AWS.
    - A business profile may supply its own repository URL/path, branch/ref, author identity, and credential secret reference; when present, those settings override the global Git settings for campaigns under that business profile.
    - Continue storing raw tokens/private keys only in AWS Secrets Manager or ECS task secrets, with RDS holding secret references and non-sensitive metadata.
    - Restrict business-profile credential management to Primary Admin/Admin users and audit all create/update/rotation events with the target business profile.
