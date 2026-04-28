# GPMPE — Design Document (Draft)

> **Status:** Draft — covers high-level architecture and the chat command interface in detail. A full drill-down covering renderer internals, YAML round-trip specification, artifact pipeline, and template binding is tracked in PLAN.md Step 11.

---

## 1. Overview

GPMPE (General Purpose Marketing Promotions Engine) is a tool that lets small businesses produce print-ready marketing flyers and posters from structured data without requiring a graphic designer.

The core idea: all business-specific information (branding, address, hours, contact details) and all promotion-specific information (offers, component sections, pricing lists) live in a database. The user edits campaigns through a chat-style interface. GPMPE combines those two sources and renders a fixed, professional PDF.

### Design Goals

- **General purpose**: the promotion engine must support arbitrary promotion shapes — not just the one flyer format it was originally built for.
- **Local-first**: all data, artifacts, and configuration live on the user's machine or in a container the user controls. No cloud dependency.
- **Single container**: one Docker image serves both the Next.js frontend and the FastAPI backend.
- **Durable data model**: business and campaign data are stored in SQLite at runtime and mirrored as a YAML tree for version control and portability.
- **Simple editing interface**: chat commands are deterministic regex-routed mutations. AI/LLM is an optional enhancement, not a requirement.
- **Extensible**: adding a new promotion shape should require only new YAML data and a new template — not code changes.

---

## 2. Architecture

### Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js (App Router), React, TypeScript, Tailwind CSS v4 |
| Backend | Python 3.12, FastAPI, Uvicorn |
| Database | SQLite (auto-created at `backend/data/gpmpe.db`) |
| AI (optional) | OpenRouter API (`openai/gpt-oss-120b`) via `OPENROUTER_API_KEY` |
| Deployment | Single Docker container (multi-stage build) |

### Request Flow

```
Browser
  └─▶ Next.js static export (served by FastAPI StaticFiles)
        └─▶ FastAPI API endpoints
              ├─▶ SQLite (runtime state)
              ├─▶ YAML tree (DATA_DIR, write-back on each mutation)
              └─▶ Renderer (PDF generation)
```

### Docker Multi-Stage Build

1. **Stage 1 (node:22-alpine):** installs frontend deps, runs `npm run build`, produces `out/`.
2. **Stage 2 (python:3.12-slim):** installs `uv`, copies `out/` to `backend/app/static/`, runs uvicorn.

---

## 3. Data Model

### Core Entities

#### `businesses`
Permanent business identity. One row per business.

| Field | Purpose |
|---|---|
| `legal_name` | Full legal business name |
| `display_name` | Short name used in UI and file paths |
| `timezone` | IANA timezone for date display |
| `is_active` | Soft-delete flag |

Related tables: `business_contacts` (phone, email, website), `business_locations` (address, hours), `brand_themes` (colors, font, logo).

#### `campaigns`
One row per marketing promotion. Many campaigns per business.

| Field | Purpose |
|---|---|
| `campaign_name` | Human-readable promotion name |
| `campaign_key` | Optional secondary key (e.g. year) for duplicate names |
| `title` | Display headline for the promotion |
| `objective` | Internal description of the campaign goal |
| `footnote_text` | Promotion-wide disclaimer text |
| `status` | `draft` · `active` · `paused` · `completed` · `archived` |
| `start_date` / `end_date` | Promotion validity window |

Campaign identity is the composite of `business_id + campaign_name + campaign_key`. Two campaigns with the same name must have different keys.

#### `campaign_components`
Ordered sections within a campaign. Each component maps to a named block in the rendered PDF.

| Field | Purpose |
|---|---|
| `component_key` | Slug used in chat commands and YAML |
| `component_kind` | `featured-offers` · `weekday-specials` · `discount-strip` · `legal-note` |
| `display_title` | Rendered section heading |
| `subtitle` | Optional secondary heading |
| `description_text` | Optional body copy |
| `footnote_text` | Component-level footnote (marker `**` appended to title) |
| `display_order` | Sort position within the campaign |

#### `campaign_component_items`
Line items within a component. Each item is one priced service, product, or note.

| Field | Purpose |
|---|---|
| `item_name` | Display name of the service or product |
| `item_kind` | `service` · `product` · `package` · `promo-note` |
| `duration_label` | Optional duration or size label (e.g. `60 min`) |
| `item_value` | Price or value text (e.g. `$85`) |
| `description_text` | Optional supporting copy |
| `terms_text` | Optional item-level fine print |
| `display_order` | Sort position within the component |

#### Supporting tables (abbreviated)

| Table | Purpose |
|---|---|
| `campaign_offers` | Flat offer list with validity windows |
| `campaign_assets` | Images, logos, and media with MIME metadata |
| `template_definitions` | Reusable layout definitions (flyer, poster) |
| `campaign_template_bindings` | Campaign-to-template selection and overrides |
| `generated_artifacts` | Rendered PDF records with path, checksum, and status |

---

## 4. Data Storage

GPMPE uses two stores together:

| Store | Config key | Default | Purpose |
|---|---|---|---|
| SQLite | `DATABASE_PATH` | `./backend/data/gpmpe.db` | Runtime API and rendering |
| YAML tree | `DATA_DIR` | `./data` | Version control, portability, write-back |

On startup GPMPE compares both sides. If they differ, the user is presented with a choice: load YAML into the DB, overwrite YAML from the DB, or use the most recent (recommended). After resolution, the app is ready.

On every mutation, GPMPE writes the updated campaign back to the YAML tree so the YAML files always reflect current state.

### YAML Directory Layout

```
DATA_DIR/
  <business-display-name>/
    <business-display-name>.yaml
    <campaign-name>/
      <campaign-name>.yaml
```

Campaign YAML files declare an ordered `components:` list, each with nested `items:`.

---

## 5. Chat Command Interface

### Architecture

Chat command handling uses a **regex-first deterministic router** in `backend/app/chat.py`. Each incoming message is tested against a priority-ordered list of compiled patterns. The first match produces a `ParsedCommand` dataclass that is passed to `apply_chat_command()`.

If `OPENROUTER_API_KEY` is configured, an LLM is called first to translate free-form natural language into a structured command string, which then goes through the same regex router. The LLM is optional; all commands work without it.

### Session Context

The chat store (`ChatSessionStore`) holds two transient per-session values:

- **`active_campaign_id`** — set automatically from the campaign selected in the UI. Changing campaigns clears the component context.
- **`active_component_ref`** — set automatically from the `component_key` referenced in the last successful component or component-item command. Allows subsequent item commands to omit the component name.

Context is in-process memory only. It is not persisted to the database.

### Field Name Aliases

Every field supports short/natural names as well as the canonical database column name. The word `field` is always optional. The leading verb can be `set`, `change`, or `update`.

**Campaign fields**

| You can say | Canonical field |
|---|---|
| `title`, `headline`, `header` | `title` |
| `objective`, `goal` | `objective` |
| `footnote`, `note`, `footnote_text` | `footnote_text` |
| `status` | `status` |
| `start`, `starts`, `start_date` | `start_date` |
| `end`, `ends`, `end_date` | `end_date` |

**Business profile fields**

| You can say | Canonical field |
|---|---|
| `display name`, `display_name`, `business name`, `name` | `display_name` |
| `legal name`, `legal_name` | `legal_name` |
| `timezone`, `time zone` | `timezone` |
| `active`, `enabled`, `is_active` | `is_active` |
| `phone`, `phone number` | `phone` |
| `street`, `street address`, `address line 1`, `address_line1` | `address_line1` |
| `suite`, `unit`, `address line 2`, `address_line2` | `address_line2` |
| `city` | `city` |
| `state`, `province` | `state` |
| `postal code`, `zip`, `zip code`, `postal_code` | `postal_code` |
| `country` | `country` |

**Brand fields**

| You can say | Canonical field |
|---|---|
| `primary`, `primary_color` | `primary_color` |
| `secondary`, `secondary_color` | `secondary_color` |
| `accent`, `accent_color` | `accent_color` |
| `font`, `font_family` | `font_family` |
| `logo`, `logo_path` | `logo_path` |

**Offer fields**

| You can say | Canonical field |
|---|---|
| `value`, `discount`, `amount`, `offer_value` | `offer_value` |
| `start`, `starts`, `start_date` | `start_date` |
| `end`, `ends`, `end_date` | `end_date` |
| `terms`, `terms_text` | `terms_text` |

**Component fields**

| You can say | Canonical field |
|---|---|
| `name`, `key`, `component_key` | `component_key` |
| `kind`, `type`, `component_kind` | `component_kind` |
| `title`, `display title`, `display_title` | `display_title` |
| `subtitle`, `subheading` | `subtitle` |
| `description`, `desc`, `description_text` | `description_text` |
| `footnote`, `note`, `footnote_text` | `footnote_text` |

**Component item fields**

| You can say | Canonical field |
|---|---|
| `value`, `price`, `cost`, `item_value` | `item_value` |
| `duration`, `duration_label` | `duration_label` |
| `description`, `desc`, `description_text` | `description_text` |
| `terms`, `terms_text` | `terms_text` |
| `name`, `item_name` | `item_name` |
| `kind`, `type`, `item_kind` | `item_kind` |

### Command Reference

#### Campaign field edits

```
set headline to "Summer Savings Event"
change the title to Weekend Blowout
set footnote to Restrictions apply. See store for details.
update status to active
set start to 2026-05-01
```

#### Business profile field edits

```
set business display name to Merci Wellness
set business active to false
change business city to Teaneck
set business postal code to 07666
```

Address behavior note:
- Business address fields map to `business_locations` rather than the core `businesses` table.
- Once any address value is present, updates are validated as a complete address shape requiring `address_line1`, `city`, `state`, and `postal_code`.

#### Brand field edits

```
set brand primary to #ecad0a
change brand font to Georgia
set brand logo to /assets/logo.png
```

#### Offer field edits

```
set offer 1 discount to 20%
set offer 2 terms to Valid on weekdays only
```

#### Component field edits

The component can be referenced by `component_key` or `display_title`.

```
change the kind of the other-services component to legal-note
change the subtitle of the other-services component to Weekday Specials
change the description of the other-services component to Neighborhood appreciation offers
change the footnote of the other-services component to Offers valid Monday through Thursday only
set component other-services title to Other Services
```

#### Component item field edits

Items can be referenced by **name** or by **ordinal** (`first`, `second`, `last`, `2nd`, etc.). The component name can be omitted when an active component context is established.

```
set the value of the Swedish Massage item to $85
change the price of the second item in the main-street-appreciation component to $80
change the duration of the Express Facial item to 45 min
change the description of the Hot Stone item to Heated stone therapy
```

#### Component rename

```
change the name of the weekday-specials component to other-services
rename the component weekday-specials to other-services
```

#### Component item clone

```
clone the Swedish Massage item and add it between the Swedish Massage and the Deep Tissue items
create a new item like the Swedish Massage item called Lymphatic Drainage and add it between the Swedish Massage and the Deep Tissue items
```

#### Component item delete

```
delete the second item in the main-street-appreciation component
delete the last item in the main-street-appreciation component
delete the Swedish Massage item in the main-street-appreciation component
delete the Swedish Massage item
```

After deletion, display order is resequenced (1, 2, 3 …).

#### Component delete

```
delete the weekday-specials component
```

The active component context is cleared automatically.

#### Query commands

```
what are the components of the current promotion
list the components
what are the items of the current component
list the items
```

#### Campaign clone (via chat)

```
clone merci-may-sales and rename it to main-street-appreciation
cloning the summer-sale promotion and renaming it to fall-clearance
```

Creates a new campaign directory + YAML + DB record and makes it the active campaign.

#### Active component context (explicit)

Normally set automatically, but can be declared explicitly:

```
I am working on the weekday-specials component
use the main-street-appreciation component
```

### Parser Routing Order

Patterns are tested in this order to prevent ambiguity:

1. Campaign / business / offer / brand field edits
2. Component field edits, set forms, and rename / key variants
3. Component item field change
4. Component item clone
5. Component item delete *(before component delete to prevent ambiguity)*
6. Component delete
7. Query commands (list components / list items)
8. Context commands (handled before the main router in `post_chat_message`)
9. Campaign clone (handled before the main router in `post_chat_message`)

Additional notes:
- `name` continues to mean `component_key` when editing a component, not `display_title`.
- `kind` on a component maps to `component_kind`; `kind` on an item maps to `item_kind`.
- The optional LLM translation path is constrained to the same canonical fields as the regex router so both paths produce the same mutation behavior.

---

## 6. Rendering Pipeline

> **TODO (Step 11 drill-down):** Full specification of the renderer, template binding resolution, component footnote marker logic, N-up PDF output, and artifact lifecycle.

High-level summary:

1. `render_campaign_artifact()` in `backend/app/renderer.py` is called with a campaign ID and artifact type (`flyer` or `poster`).
2. The renderer queries the DB for the full campaign snapshot: business profile, brand theme, ordered components, and nested items.
3. It resolves the effective template (default values merged with campaign-level overrides).
4. It generates a PDF using the resolved layout and writes it to `OUTPUT_DIR`.
5. It records the artifact in `generated_artifacts` with a checksum and status.

Component footnote rendering:
- If a component has `footnote_text`, the marker ` **` is appended to the component's rendered title.
- The footnote text is rendered in the bottom area of the component panel.
- Campaign-level `footnote_text` is rendered at the bottom of the flyer as a promotion-wide note.

Optional N-up output: if `IMAGES_PER_PAGE=N` is set in `.config`, a second PDF is generated at `<campaign>-<N>p.pdf` with N images per page.

---

## 7. YAML Round-Trip (Draft)

> **TODO (Step 11 drill-down):** Full field-by-field specification of the YAML schema, sync semantics, and write-back determinism.

Key rules (current):

- Startup sync is authoritative: YAML-managed records not present in the YAML tree are removed from the DB.
- Every mutation writes the full updated campaign back to YAML immediately (not just on save).
- Component order and item order round-trip via `display_order` and list position in YAML.
- Non-filesystem-safe business or campaign names are treated as startup validation errors.

---

## 8. Configuration

Runtime configuration lives in a `.config` file at the repo root using `KEY=VALUE` format.

| Key | Purpose | Default |
|---|---|---|
| `DATABASE_PATH` | SQLite database path | `./backend/data/gpmpe.db` |
| `DATA_DIR` | YAML data tree root | `./data` |
| `OUTPUT_DIR` | PDF artifact output directory | `./output` |
| `OPENROUTER_API_KEY` | LLM translation (optional) | *(unset)* |
| `IMAGES_PER_PAGE` | N-up PDF output (optional) | *(unset)* |
| `COMMIT_ON_SAVE` | Auto git commit on save | `false` |
| `GIT_REPO_PATH` | Repository path for git commits | *(unset)* |
| `GIT_USER_NAME` | Git author name for commits | *(unset)* |
| `GIT_USER_EMAIL` | Git author email for commits | *(unset)* |
| `TEST_DATABASE_PATH` | Isolated test database path | *(unset)* |
| `TEST_DATA_DIR` | Isolated test YAML tree | *(unset)* |

Test path overrides (`TEST_DATABASE_PATH` + `TEST_DATA_DIR`) must be set together or neither takes effect.

---

## 9. Design Tokens

Defined as CSS variables in `frontend/src/app/globals.css`:

| Token | Value | Use |
|---|---|---|
| Accent yellow | `#ecad0a` | Primary CTA, highlights |
| Blue primary | `#209dd7` | Links, headers |
| Purple secondary | `#753991` | Secondary actions |
| Dark navy | `#032147` | Body text, backgrounds |

---

## 10. Testing Strategy

- **Backend**: pytest with `TestClient` (FastAPI). Each test function gets a fresh in-memory SQLite DB via `tmp_path` and `monkeypatch`.
- **Frontend unit**: Vitest + React Testing Library.
- **Frontend E2E**: Playwright on port 3100 (not 3000).
- **Coverage target**: 80% across backend.
- Startup scripts include readiness checks to avoid false failures from immediate post-start integration calls.

---

## 11. What Is Not In Scope

- Multi-user / multi-tenant access control.
- Cloud database (targeted at a future AWS RDS migration).
- Real-time collaboration.
- AI content generation (LLM is translation-only, not content authoring).
- Revision history or audit log.
- Design tooling — layouts and formatting use predefined templates.
