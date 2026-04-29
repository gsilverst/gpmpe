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

### Step 12: Repository Visibility Cutover (Private -> Public) (TODO)
Objective:
- Change repository visibility to public only after explicit completion sign-off.

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

### Step 19: Campaign Builder GUI Enhancements (TODO)
Objective:
- Improve the "Campaign Builder" part of the application GUI to provide a full alternative to the chatbot.
- At a minimum, add "Add Item" and "Edit Item" options for all components.
- Ensure all relevant database fields are editable through the web forms.

### Step 20: Implement Missing Chat Commands (TODO)
Objective:
- Based on the findings from Step 16, implement all missing natural-language commands required for 100% campaign-building parity via chat.

### Step 21: Externalize Renderer Layout Constants (TODO)
Objective:
- Based on the proposal from Step 17, refactor `renderer.py` and the database schema to support dynamic, data-driven overrides for visual layout properties.

### Step 22: Detailed Requirements Documentation (TODO)
Objective:
- Write a comprehensive requirements document that captures the original intent and evolution of the project.
- Document the functional, technical, and aesthetic requirements realized in the current system.
- Output: `docs/REQUIREMENTS.md`.
