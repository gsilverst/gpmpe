# GPMPE: General Purpose Marketing Promotions Engine
## Product Requirements Document (Retrospective & Baseline)

### 1. Executive Summary
GPMPE is a robust, data-driven system designed to automate the creation and management of marketing promotions (flyers and posters). It evolved from a specialized script into a generalized platform that prioritizes high-fidelity rendering, natural language editing, and source-controlled data integrity.

### 2. Core Intent & Evolution
The original project aimed to take a proprietary flyer generator and refactor it for broader utility. The system has evolved from a linear generation script into a bidirectional ecosystem where natural language (Chat) and visual forms (GUI) are secondary interfaces to a persistent, authoritative data layer (YAML/SQLite).

### 3. Functional Requirements

#### 3.1 Data Management & Synchronization
- **Authoritative YAML Storage**: All campaign and business data must be stored in a human-readable, repository-managed YAML tree (`./data`).
- **Runtime Working Store**: The application uses a local SQLite database for performance and relational queries.
- **Startup Reconciliation**: On launch, the system must detect discrepancies between YAML files and the SQLite database, forcing a resolution (Overwrite DB or Overwrite YAML) to maintain consistency.
- **Immediate Persistence**: Edits made via Chat or GUI must write back to the YAML files immediately.

#### 3.2 Campaign Composition & Layout
- **Multi-Section Logic**: Promotions are composed of "Components" (e.g., Header, Featured Offers, Weekday Specials, Legal Note).
- **Component Kinds**: The system supports specialized rendering modes (e.g., `offer-card-grid`, `strip-list`, `discount-panel`) mapped to component kinds.
- **Item Ordinality**: Items within sections support strict display ordering.

#### 3.3 Natural Language Interface (Chatbot)
- **Context-Aware Commands**: Commands like "set title to..." or "delete item 1" apply to the active campaign or active component context automatically.
- **Structural Mutations**: Users can rename components, add items, move items, and clear specific fields (e.g., "delete the footnote for featured") using natural language.
- **Advanced Routing**: The bot must handle complex phrasing, including ordinals ("first", "last", "2nd") and exact name matching.
- **Self-Correcting UI**: Incomplete commands (e.g., "rename component") trigger clarification prompts instead of failures.

#### 3.4 Artifact Generation (PDF)
- **High-Fidelity Rendering**: Outputs must mirror professional designs with precise margins (36pt), mathematical vertical symmetry, and specialized typography (Helvetica/Times).
- **Dual PDF Support**: When configured (via `IMAGES_PER_PAGE`), the system must generate both a primary flyer and a scaled "n-up" version on a single page.
- **Strict Naming Convention**: Files must be named `company-campaign.pdf` and `company-campaign-Np.pdf` without auto-incrementing suffixes.
- **Collision Management**: If a file exists locally, the system must prompt the user to "Replace" or "Rename" via a custom UI modal, rather than silently overwriting or relying on browser-native downloads.

### 4. Technical Requirements
- **Deployment**: Single Docker container serving both the Next.js frontend and FastAPI backend.
- **Configuration**: Simple `.config` file in the repository root (e.g., `IMAGES_PER_PAGE=4`).
- **Environment**: Local-first development and execution on MacOS/Linux/Windows.
- **Security**: No proprietary client data in public repository paths (`local/` used for private experimentation).

### 5. Aesthetic & UX Standards
- **Vertical Symmetry**: Cards in the `featured-offers` section must use calculated centering for labels (Duration sits balanced between Name baseline and Price top).
- **Responsive Workspace**: The UI uses a split-pane layout with the chat interface as a persistent sidebar for real-time iteration.
- **Live Preview**: Generated artifacts must appear in an inline PDF viewer immediately after generation.

### 6. Success Metrics
- **100% Parity**: All campaign features can be built entirely via Natural Language or entirely via the Campaign Builder GUI.
- **Determinism**: Identical YAML input always produces pixel-perfect identical PDF output.
- **Git Compatibility**: The state of the promotion engine can be fully tracked and branched via standard Git workflows on the YAML directory.
