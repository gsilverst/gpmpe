# GPMPE Implementation Plan

## Goals
- Refactor an existing proprietary single-promotion flyer generator into a general-purpose marketing promotions engine.
- Keep deployment as a single Docker container serving frontend and backend.
- Use a simple SQLite-first approach with a persistent local database.
- Generate fixed PDF outputs and persist only the current application state needed to recreate them.
- Support YAML as the repository-facing campaign data format so users can store campaign/business data in version control outside the runtime database.

## Delivered Updates (April 2026)
- Startup reconciliation now enforces a required choice path; there is no "continue as-is" bypass.
- Main UI flow now supports stronger business/campaign editing parity:
  - Business profile includes address and phone fields.
  - Campaign builder mirrors profile-style list/create/edit UX.
- Campaign cloning flow now supports deterministic conflict handling for duplicate names and optional secondary key capture.
- Embedded PDF preview is now inline and auto-regenerated after changes, with a manual refresh action retained.
- Workspace layout now places the chatbot in a right-side panel on desktop.
- Chat command handling now supports component key and display-title edits with broader natural-language forms:
  - Rename component key by natural language.
  - Rename component key using explicit "component-key field" phrasing.
  - Update component display title through explicit component field commands.
- Chat command handling now supports nested component-item edits:
  - Update component item fields by ordinal selector (`first`, `second`, `last`, `2nd`, etc.).
  - Update component item fields by exact item name.
- Chat session context now tracks active campaign and active component state:
  - Active campaign is updated automatically from the current editing target.
  - Active component is updated automatically from successful component/component-item references.
  - Renaming a component immediately moves active component context to the new component key.
  - Changing campaigns clears stale component context automatically.
- Incomplete component-rename messages now return a successful clarification response (`target=clarify`) instead of a hard HTTP 400 failure.

## Execution Checkpoint (April 28, 2026 - Late Evening)

Current phase status:
- Completed: Step 16 (Data and Command Gap Analysis).
- Completed: Step 17 (Renderer Tunability and Visual Documentation).
- Completed: Step 18 (User Guide: Chatbot Communication).
- Completed: Step 13, 14, 15 (Design, Externalization, Sample Data).

Known current baseline:
- Gap report available at `docs/GAP_REPORT.md`.
- Tunability proposal available at `docs/RENDERER_TUNABILITY.md`.
- Chat User Guide available at `docs/USER_GUIDE_CHAT.md`.
- Backend tests fully green (145 passed).

Approved next steps (strict order):
1. Step 12: Repository Visibility Cutover (Private -> Public).
2. Step 19: Campaign Builder GUI Enhancements (Add/Edit Item support).
3. Step 20: Implement Missing Chat Commands (Parity work).
4. Step 21: Externalize Renderer Layout Constants (Tunability work).

Notable new/updated backend tests:
- `test_chat_message_can_rename_component_by_natural_language`
- `test_chat_message_can_rename_component_by_display_title`
- `test_chat_message_can_rename_component_key_with_component_key_field_phrase`
- `test_chat_message_component_rename_without_new_name_returns_helpful_error`
- `test_chat_message_component_key_field_phrase_without_new_name_returns_helpful_error`
- `test_chat_message_can_update_component_item_field_by_ordinal`
- `test_chat_message_can_update_component_item_field_by_item_name`
- `test_chat_message_can_set_active_component_context_and_edit_item_without_component_name`
- `test_component_rename_updates_active_component_context_automatically`
- `test_changing_campaign_clears_stale_component_context`
- `test_collect_render_context_includes_template_and_render_shape`
- `test_render_flyer_uses_data_defined_component_region`
- `test_chat_message_can_add_new_item_with_positioning`
- `test_chat_message_can_add_new_item_with_an_item_and_no_name`

## Working Assumptions (to confirm)
- Early implementation may start with one active campaign path per business, but the schema and API must extend cleanly to many campaigns per business.
- Only the current state needs to be stored in the application database.
- PDF files are stored on disk in a configurable output directory that defaults to the current directory.
- Local configuration uses a simple repo-root `.config` file with `KEY=VALUE` entries.
- Chat history is transient local process state and is not persisted in the database.
- Frontend and backend are built in one repo and shipped in one container.
- A standalone data-manager app will be added for direct SQLite business/campaign viewing and creation, starting with a single-business/single-campaign MVP import path from YAML.
- A configurable `DATA_DIR` value in `.config` points to the repository-managed YAML tree and defaults to `./data`.
- YAML files are the repository-facing campaign/business format; SQLite is the runtime working store used by the application.
- On GUI startup, if `DATA_DIR` is configured, the application reads/syncs it automatically; if the directory is missing, the application creates it.
- If `DATA_DIR` is not configured, that is an error in MVP.
- Prompting the user to choose a data directory and updating `.config` without restart is a future enhancement, not part of MVP.

## Step-by-Step Plan

### Step 1: Repository Bootstrap and Baseline Contracts (COMPLETED)
### Step 2: Core Data Model (Business + Campaign) (COMPLETED)
### Step 3: Promotion Composition Model (COMPLETED)
### Step 4a: Standalone SQLite Data Manager + YAML Import MVP (COMPLETED)
### Step 4b: Main-App Advanced Editing Integration + YAML-Backed Editing (COMPLETED)
### Step 5: Artifact Pipeline (Fixed PDF Output) (COMPLETED)
### Step 5a: Promotion Component Model (Multi-Section Promotions) (COMPLETED)
### Step 5b: Test Database and Test Data Directory Overrides (COMPLETED)
### Step 6: API Surface and Frontend Integration (COMPLETED)
### Step 7: Security, Validation, and Operational Hardening (COMPLETED)
### Step 8: Containerization and Local Runtime Workflow (COMPLETED)
### Step 9: Data Migration Path from Proprietary Reference Implementation (COMPLETED)
### Step 10: One-Line Application Startup (COMPLETED)
### Step 10a: Campaign Cloning via Chat (COMPLETED)
### Step 11: LLM-Backed Chat Interface (COMPLETED)

### Step 13: DESIGN.md Completion and Technical Reference (COMPLETED)
Objective:
- Finalize documentation to reflect the generalized, data-driven architecture.
- Document the full natural-language command grammar (including positioning and plural support).
- Define the authoritative sync/write-back flow for public contributors.

### Step 14: Renderer Data Externalization (DB-Driven Campaign Semantics) (COMPLETED)
Objective:
- Remove campaign-specific and layout-specific assumptions from renderer code so campaign behavior is represented explicitly in database objects.

### Step 15: Sample Data Directory (Fictitious Company) (COMPLETED)
Objective:
- Create a comprehensive sample data directory (`data/`) under source control to demonstrate GPMPE capabilities with a fictitious company and multiple promotions.

### Step 12: Repository Visibility Cutover (Private -> Public) (COMPLETED)
Objective:
- Change repository visibility to public.
- Project is now open for public release and baseline usage.

## Phase 4: Enhancements, Analysis, and User Experience

### Step 16: Data and Command Gap Analysis (COMPLETED)
Objective:
- Identify any gaps between the data stored in the database/YAML files and the mutation capabilities of the chatbot interface.
- Ensure the chatbot can handle *all* tasks related to building and modifying a campaign.
- Output: A gap report and a prioritized list of new chat commands to implement (`docs/GAP_REPORT.md`).

### Step 17: Renderer Tunability and Visual Documentation (COMPLETED)
Objective:
- Identify and document all visual aspects of the generated PDF that are currently hard-wired in `renderer.py` (e.g., specific padding, font choices, layout proportions).
- Make a proposal on which of these features should be externalized as tunable fields in the YAML/database objects (e.g., via the `style_json` or `layout_json` fields).
- Output: Tunability roadmap (`docs/RENDERER_TUNABILITY.md`).

### Step 18: User Guide: Effective Chatbot Communication (COMPLETED)
Objective:
- Create a comprehensive User Guide that provides detailed guidance on how to effectively communicate with the chatbot.
- Include examples for entering data, renaming components, adding items with specific positioning, and cloning campaigns.
- Output: Comprehensive NL command reference (`docs/USER_GUIDE_CHAT.md`).

### Step 18b: Dual PDF Generation & Strict Naming (COMPLETED)
Objective:
- Enforce strict `company-campaign.pdf` naming convention.
- Support `IMAGES_PER_PAGE` config for secondary n-up artifact (`company-campaign-Np.pdf`).
- Implement custom "Replace or Rename" modal to handle local file collisions without browser-injected suffixes.

### Step 19: Campaign Builder GUI Enhancements (COMPLETED)
Objective:
- Improve the "Campaign Builder" part of the application GUI to provide a full alternative to the chatbot.
- Implemented card-based section list with integrated item management.
- Added Add/Edit Section and Add/Edit Item modals covering all relevant schema fields.
- Enabled immediate YAML write-back for all GUI-driven mutations.

### Step 20: Implement Missing Chat Commands (COMPLETED)
Objective:
- Based on the findings from Step 16, implemented all missing natural-language commands for 100% building parity.
- Added structural commands: `add component <kind> named <title>`, `delete campaign <name>`, `add offer <name>`, `delete offer <id>`.
- Enabled mutation for advanced fields: `render_region`, `render_mode`, `render_role`, `email`, `website`, `footer`, `legal`.
- Implemented deep style overrides: `set <component> style <key> to <value>`.

### Step 21: Externalize Renderer Layout Constants (COMPLETED)
Objective:
- Refactored `renderer.py` to move hard-coded visual constants into a data-driven `_DEFAULT_RENDER_LAYOUT`.
- Implemented support for `typography` and `geometry` overrides via template-level `layout_json`.
- Enabled component-level style overrides (e.g., `border_radius`) via `style_json`.
- Verified 100% parity and visual consistency across all rendering modes.

### Step 21a: Administrator Settings & Credential Management Portal (PARTIAL / TODO)
Objective:
- Add an administrator-only web interface for managing runtime settings and external service credentials in both local and AWS deployments.
- Allow Primary Admin/Admin users to configure the business data repository remote URL, branch/ref, Git author identity, push policy, and credential reference used by the runtime Git sync worker.
- Include administrator user management in the same administrative area, including adding users, assigning Primary Admin/Admin/Regular roles, and managing business-profile access.
- Keep raw Git tokens, private keys, database passwords, API keys, and other sensitive values out of normal application tables; store only non-sensitive metadata and credential references in the application database.
- Support local deployments with a local secret/reference mechanism and AWS deployments with AWS Secrets Manager or ECS task secrets.
- Support credential create/update/rotation workflows without exposing secret values back to the browser after save.
- Add audit logging for credential and repository configuration changes, including actor, timestamp, scope, repository metadata, and rotation timestamp.
- Restrict credential administration to Primary Admin/Admin users; regular users must not be able to view or modify runtime credentials.
- Start with global Git credentials shared across all business profiles; business-profile-specific credential overrides can follow after the global flow is validated.
- Current status: a basic admin Git settings page, metadata model, local/AWS secret-provider abstraction, and audit-log endpoint exist. Full user management, authenticated admin-only enforcement, and complete credential administration UX are not yet implemented.
- Update the user guide with a dedicated administrator section covering the admin page, user management, role assignment, business-profile access, runtime configuration, business data repository setup, credential rotation, and audit-log review.

### Step 21b: Version-Control-Aware Save and Restore UX (TODO)
Objective:
- Treat the promotion Save action as meaningful only when version control for the business data repository is configured.
- Disable/grey out the campaign Save button when the administrator has not configured the required Git repository path, author identity, and credential reference/secret.
- Surface a clear non-technical message that saving requires administrator-configured version control, without exposing Git implementation details to regular users.
- Add a nice-to-have campaign-level version restore flow that lets a user choose an older marketing campaign version by date/time and restore it as the current campaign state.
- Hide Git details such as commit IDs, branch names, and repository mechanics from regular campaign users.
- When a restored campaign is modified and saved, commit it as a new linear version of the campaign rather than creating a branch.
- Keep campaign version restore scoped to marketing campaigns only for regular users.
- Add a similar administrator-only nice-to-have restore flow for business profiles, since only admins may add or modify business profiles.

### Step 21c: Renderer Parameterization Expansion (TODO)
Objective:
- Continue moving rendering decisions out of hard-coded renderer branches and into database/YAML-controlled template, component, and item parameters.
- Audit real campaign examples, including promotions where visually similar components display differently, to identify which differences come from `component_kind`, `render_region`, `render_mode`, style defaults, item roles, or renderer-only heuristics.
- Expand structured template `layout_json`, template default values, component `style_json`, item `style_json`, `render_mode`, and `render_role` contracts so campaign-specific display behavior can be represented as data.
- Preserve backwards compatibility by keeping renderer defaults for older data while allowing explicit database/YAML values to override those defaults.
- Backfill explicit values into existing campaign data when renderer defaults are externalized, so historical campaigns keep rendering as close as practical to their prior output.
- Document each newly externalized rendering parameter in `docs/DESIGN.md` and the user/admin documentation, including defaults and migration behavior.

### Step 21d: Friendly Chatbot Renderer-Style Commands (TODO)
Objective:
- Upgrade the chatbot from explicit style-key edits toward natural style intent commands such as "make the featured subtitle darker", "make the item durations bolder", or "increase the subtitle size".
- Map friendly visual intents to approved renderer parameters in `style_json`, `layout_json`, or template override values while keeping the stored data explicit.
- Support both component-level style edits and item-level style edits, including typography controls such as subtitle font, subtitle size, subtitle color, duration font, duration color, and related print-readability settings.
- Add validation and helpful error messages for supported font names, numeric sizes, color values, and style scopes so users do not need to know internal JSON keys.
- Keep advanced explicit commands such as `set <component> style <key> to <value>` available for power users and debugging.
- Add neutral tests and user-guide examples for common print-readability adjustments without relying on proprietary campaign data.

## Phase 5: AWS Migration

### Step 23: Database Abstraction (SQLAlchemy) (COMPLETED)
Objective:
- Defined SQLAlchemy 2.0 models mirroring the SQLite schema.
- Added SQLAlchemy, Alembic, and RDS drivers to dependencies.
- Refactored `db.py` and `config.py` to support dynamic `DATABASE_URL`.
- Implemented hybrid initialization using `Base.metadata.create_all` and legacy scripts.

### Step 24: Storage & Filesystem Parity (Amazon EFS) (COMPLETED)
Objective:
- Implemented atomic file writing (`_atomic_write`) for YAML and PDFs to handle cloud filesystem concurrency.
- Updated `docker-compose.yml` to use named volumes and environment variable overrides for `DATA_DIR` and `OUTPUT_DIR`.
- Hardened the `Dockerfile` with required system dependencies and pre-created mount points.
- Ensured the application is fully agnostic of directory locations, ready for EFS mounting.

### Step 25: Version Control Sync Worker (COMPLETED)
Objective:
- Implemented `pull_latest_changes` in `git_store.py` to bring repository updates into the local environment.
- Added `/data/pull` API endpoint to automate the "Git Pull -> DB Sync" workflow.
- Updated `auto_commit_paths` to perform an automatic `git push` after local edits (Chat/GUI).
- Enabled bidirectional synchronization between the application and the authoritative YAML repository.

### Step 26: CI/CD Dual Build Infrastructure (TODO)
Objective:
- Provide deployment scaffolding that deployment owners can copy/adapt into their own deployment repository to build Docker images and deploy to Amazon ECR/ECS.
- Support a `RUN_MODE=aws|local` toggle for environment-specific behaviors.
- Keep application source control, deployment automation, and business/campaign data repositories separate.
- Integrate the administrator-managed runtime credential model from Step 21a with AWS Secrets Manager or ECS task secrets.

## Phase 6: Post-AWS Data Model and Workspace Evolution

### Step 27: Explicit Data Schema Versions (POST-AWS TODO)
Objective:
- Add explicit version fields for repository-facing YAML/business/campaign data, separate from the existing database migration `schema_version` stored in `app_meta`.
- Version each business profile and campaign document so the application can identify which data contract produced it.
- Add migration code that can upgrade older YAML/database records to newer data schema versions.
- When renderer defaults are externalized into database/YAML parameters, migrate existing data by writing explicit values for the old defaults so rendering behavior is preserved even if future software defaults change.
- Include schema-version metadata in YAML round-trip, import/export, startup reconciliation, and Git sync flows.
- Add tests proving older schema versions load, migrate deterministically, preserve rendering intent, and write back using the current schema version.
- Document the difference between database migration versioning and business/campaign data schema versioning.

### Step 28: Backwards Compatibility and Release Evolution Policy (POST-AWS TODO)
Objective:
- Define a compatibility policy before the first open-source release so future contributors understand which contracts should remain stable and how breaking changes are handled.
- Treat repository-facing YAML schemas, database migration paths, API response shapes, configuration keys, admin/runtime settings, and renderer data contracts as compatibility-sensitive surfaces.
- Require explicit migration paths for database and YAML/data-schema changes whenever practical.
- Require compatibility tests using older sample fixtures so future releases prove they can load, migrate, render, and save data created by earlier versions.
- Define deprecation rules for renamed fields, changed defaults, renderer behavior changes, configuration keys, and API fields.
- Document when a breaking change is allowed, how it should be announced, and what migration guidance must be provided.
- Keep sample data versioned across representative schema generations so backwards compatibility can be tested without relying on private/proprietary campaigns.
- Include a public release checklist item that confirms schema versioning, migration tests, compatibility notes, and upgrade documentation are in place.

### Step 29: Business-Scoped User Workspaces (POST-AWS TODO)
Objective:
- After the AWS migration is complete and the application has been successfully deployed to AWS, add user-created workspaces under each business profile.
- Workspaces are separate from the campaigns that live directly under the business profile.
- A workspace belongs to exactly one business profile. If a user has access to multiple business profiles and wants workspace organization for each one, they must create separate workspace(s) under each business profile.

Workspace modes:
- Support either a single workspace that is public or private, or separate public and private workspaces under the same business profile.
- A private workspace is visible only to the workspace owner and admin users.
- A public workspace is visible to all users who have access to campaigns for the associated business profile.

Access model:
- Admin users can view all campaigns and all workspaces associated with all business profiles.
- Regular users can view public workspaces for business profiles they have been granted access to.
- Regular users can view their own private workspaces.
- Regular users cannot view another regular user's private workspace.

Implementation considerations:
- Add a workspace data model scoped by `business_id`, with ownership, visibility (`public` or `private`), and lifecycle metadata.
- Associate campaigns with either the business profile directly or with a workspace under that business profile.
- Update campaign list/query APIs to support direct business campaigns, public workspace campaigns, and private workspace campaigns according to the requesting user's permissions.
- Update the UI to let users create, select, and manage workspaces within the active business profile.
- Ensure chatbot campaign creation and evolution can target either the business-level campaign area or a selected workspace.
- Include authorization tests for admin visibility, public workspace access, private workspace isolation, and multi-business-profile separation.

### Step 22: Detailed Requirements Documentation (COMPLETED)
Objective:
- Write a comprehensive requirements document that captures the original intent and evolution of the project.
- Document the functional, technical, and aesthetic requirements realized in the current system.
- Output: `docs/REQUIREMENTS.md`.

### Step 23: AWS Migration Strategy (COMPLETED)
Objective:
- Prepare a comprehensive plan for migrating to AWS while maintaining local parity.
- Define the dual-build architecture using SQLAlchemy and Amazon EFS.
- Detail the Git-to-Cloud synchronization mechanism for YAML version control.
- Output: `docs/AWS_MIGRATION_PLAN.md`.
