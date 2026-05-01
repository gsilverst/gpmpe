# GPMPE — Design Document (Draft)

> **Status:** Draft — covers high-level architecture and the chat command interface in detail. Renderer data-externalization findings are captured in Appendix A as the Step 14a approval artifact.

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
| `component_kind` | Content classification, e.g. `featured-offers` · `weekday-specials` · `discount-strip` · `legal-note` |
| `render_region` | Template region key used by the renderer, e.g. `featured`, `secondary`, `discount`, `legal` |
| `render_mode` | Data-defined renderer mode, e.g. `offer-card-grid`, `strip-list`, `discount-panel`, `legal-text` |
| `style_json` | Optional component-level style tokens and layout hints |
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
| `render_role` | Optional item slot or emphasis role within its component |
| `style_json` | Optional item-level style tokens and layout hints |
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

Campaign YAML files declare an ordered `components:` list, each with nested `items:`. Component and item render metadata (`render_region`, `render_mode`, `render_role`, and `style`) round-trips through YAML so template behavior can be edited as data.

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

#### Add a new item (with positioning)

The `add item` command is highly flexible. You can specify a name (optional, defaults to "New Item"), clone an existing item, and position it before or after another item. All commands are **plural-aware**; you can use `item` or `items` and `component` or `components` interchangeably.

```
add a new item called "Deep Tissue" to featured-offers after "Swedish Massage"
create an item like Swedish Massage before Hot Stone
add an item Body Sculpting to main-street-appreciation
```

Supported syntax: `add/create [a/an/the] [new] item [called <name>] [like <source>] [to/in/into <component>] [before/after <relative>]`

#### Component item clone (Legacy phrasing)

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

Appendix A inventories the renderer assumptions that still need to move from code into database-owned campaign/template data before the renderer can be considered data-driven.

High-level summary:

1. `render_campaign_artifact()` in `backend/app/renderer.py` is called with a campaign ID and artifact type (`flyer` or `poster`).
2. The renderer queries the DB for the full campaign snapshot: business profile, brand theme, ordered components, and nested items.
3. It resolves the effective template, including layout JSON and merged default/override values.
4. It groups components by `render_region` and uses `render_mode` to preserve data-defined campaign semantics instead of relying directly on `component_kind`.
5. It generates a PDF using the resolved layout and writes it to `OUTPUT_DIR`.
6. It records the artifact in `generated_artifacts` with a checksum and status.

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
| `COMMIT_ON_SAVE` | Auto git commit on save | `true` |
| `GIT_REPO_PATH` | Repository path for git commits | *(unset)* |
| `GIT_USER_NAME` | Git author name for commits | *(unset)* |
| `GIT_USER_EMAIL` | Git author email for commits | *(unset)* |
| `GIT_PUSH_ENABLED` | Push commits to the configured Git remote | `false` |
| `GIT_REMOTE` | Git remote used for pull/push operations | `origin` |
| `GIT_BRANCH` | Git branch/ref used for pull/push operations | `HEAD` |
| `GIT_LOCK_TIMEOUT_SECONDS` | Seconds to wait for the Git operation lock | `30` |
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

---

## Appendix A. Step 14a Renderer Data-Externalization Inventory

This appendix is the Step 14a approval artifact. It records the renderer assumptions that are still embedded in source code, why each assumption is campaign- or layout-specific, where the data should live after extraction, the schema gaps that block the move, and the backfill implications for existing campaigns.

Step 14a is documentation-only. Baseline and render-context tests are deferred to Step 14b so they can be added alongside the approved schema and renderer changes.

Step 14b should not begin until this appendix is reviewed and approved.

Step 14b implementation note: the first extraction pass is complete. Schema version 006 adds component `render_region`, `render_mode`, and `style_json` fields plus item `render_role` and `style_json` fields. YAML sync/write-back and render context collection round-trip those fields. The renderer now groups components by `render_region`, falls back from legacy `component_kind` only as a compatibility/defaulting path, and reads template `layout_json` into the render context for page regions and layout/style constants.

### A.1 Source-Referenced Extraction Inventory

| Embedded rule | Current implementation | Why it is campaign-specific | Proposed data owner |
|---|---|---|---|
| Letter page size and global margin are fixed at 612 x 792 points with a 36 point margin. | `backend/app/renderer.py:27-40` | A renderer can draw on a page, but the page stock, trim size, and safe area are template choices. Poster, flyer, postcard, or social formats need different bounds. | Global template: `page.size`, `page.orientation`, `page.margin` |
| Rich flyer regions use fixed header, featured, weekday, and legal coordinates. | `backend/app/renderer.py:31-40`, `backend/app/renderer.py:287-505` | The current vertical stack reflects one flyer design rather than a general promotion model. Region names and bounds should be template data. | Global template layout regions, with optional campaign override |
| Rich layout is selected by the presence of `featured-offers` or weekday-like component kinds. | `backend/app/renderer.py:780-787`, `backend/app/renderer.py:820-827` | Component semantic names currently select the whole layout mode. A campaign should bind components to template regions/render modes explicitly. | Campaign/template binding: component-to-region mapping and render mode |
| Component kinds are hardcoded into featured, weekday, discount, and legal buckets. | `backend/app/renderer.py:780-786`, `backend/app/renderer.py:820-826` | Adding a new section type or reusing an existing type in another region currently requires renderer edits. | Component: `render_mode`; binding: `region_key`; template: allowed modes |
| Only the first component in each bucket is rendered. | `backend/app/renderer.py:318`, `backend/app/renderer.py:397`, `backend/app/renderer.py:448`, `backend/app/renderer.py:488-489` | Campaigns cannot data-define multiple featured, discount, or legal sections even if the schema allows ordered components. | Template region policy: cardinality and overflow behavior |
| Palette fallbacks are hardcoded for primary, secondary, accent, background, blush, cards, legal background, and legal border. | `backend/app/renderer.py:90-114` | Defaults express the current flyer brand/look, not generic rendering behavior. | Theme tokens plus template default tokens |
| Natural-language color aliases are renderer-local. | `backend/app/renderer.py:50-87` | Color normalization affects chat, YAML, and rendering; it should be consistent outside the PDF renderer. | Shared color/token validation layer, persisted canonical values |
| Logo cleanup crops 62 px from the top and removes near-white edge-connected background pixels. | `backend/app/renderer.py:129-164` | This assumes the shape and background of a specific logo asset. Other businesses may need no crop, a different crop, or no background removal. | Business asset metadata or theme token: logo processing policy |
| Relative logos resolve under `DATA_DIR/<business_display_name.lower()>`. | `backend/app/renderer.py:167-179` | Filesystem naming is not always the lowercased display name, especially once safe path names diverge from display names. | Business/YAML asset path metadata, resolved before render context reaches renderer |
| Header panel geometry, logo size, and business text positions are fixed. | `backend/app/renderer.py:287-305` | Header composition is part of the selected template, not an invariant of all campaigns. | Template region definitions and typography slots |
| Header text uppercases the business display name. | `backend/app/renderer.py:300-304`, `backend/app/renderer.py:523-525` | Case transformation is a style choice. Some brands rely on exact casing. | Typography/text transform rule in template or theme |
| Component footnote marker is always ` **`. | `backend/app/renderer.py:307-314`, `backend/app/renderer.py:390-393`, `backend/app/renderer.py:441-444`, `backend/app/renderer.py:587-597` | Marker syntax and placement are presentation rules. Other templates may use symbols, superscripts, numbered notes, or no marker. | Template footnote policy and component/campaign footnote data |
| Featured card grid is limited to three columns with specific row, gap, min/max height, and max card width rules. | `backend/app/renderer.py:320-388` | Capacity and flow rules determine campaign content limits and should be configurable per template region. | Template region: grid constraints, item render mode, overflow policy |
| Featured title, subtitle, card, and footnote typography is fixed. | `backend/app/renderer.py:334-352`, `backend/app/renderer.py:385-393` | Font family, weight, size, leading, and color are template style decisions. | Template typography slots, theme token references |
| Featured card header accent defaults to the first item's background color. | `backend/app/renderer.py:324-328`, `backend/app/renderer.py:380-383` | This is a specific visual heuristic, not generic campaign semantics. | Component style token or template fallback expression |
| Weekday panel fill/text colors, subtitle placement, strip bounds, and max row calculation are hardcoded. | `backend/app/renderer.py:395-444` | The weekday section is a current flyer region with fixed capacity and collision behavior. | Template region bounds, item layout policy, typography slots |
| `other-offers` and `secondary-offers` are treated like `weekday-specials`. | `backend/app/renderer.py:781-784`, `backend/app/renderer.py:821-824` | Synonyms for visual behavior are embedded in code. The schema should store visual role/render mode directly. | Component render mode or component-to-region binding |
| Discount strip renders item 1 inside a white subpanel and item 2 below as italic text; remaining items are ignored. | `backend/app/renderer.py:446-474` | Item ordinal determines presentation in a highly specific way. Campaign authors need data fields for role/slot or a template item policy. | Component item: `render_role` or template item slot mapping |
| Footer text comes from `effective_values.footer` and is placed inside the weekday panel. | `backend/app/renderer.py:476-480` | Footer placement and source are template choices. Some campaigns may source footer from contacts or a component. | Template text slot bound to effective value, contact data, or component |
| Legal strip is always drawn, even when no legal component/text exists. | `backend/app/renderer.py:482-494` | Empty legal chrome may be correct for one flyer but not for all templates. | Template region visibility policy |
| Campaign footnote renders below the legal strip with a fixed two-note cap. | `backend/app/renderer.py:496-504` | Footnote capacity and placement are layout rules that may vary by template. | Template footnote area, overflow policy |
| Simple fallback flyer has a hardcoded header bar, headline block, component loop, CTA bar, footer, and note area. | `backend/app/renderer.py:511-597` | The fallback is effectively another implicit template but is not represented in template data. | Global fallback template definition with explicit regions |
| Simple fallback stops rendering components/items when hardcoded Y thresholds are reached. | `backend/app/renderer.py:538-555` | Overflow behavior changes campaign output and should be declared per region. | Template region overflow/capacity rules |
| Simple row format joins item name, duration, and value with punctuation. | `backend/app/renderer.py:553-559` | Text assembly is content formatting, not drawing infrastructure. | Item render mode or template text format string |
| Legacy `campaign_offers` are converted into an implicit `featured-offers` component named `offers`. | `backend/app/renderer.py:604-633`, `backend/app/renderer.py:749-750` | Missing component data silently creates campaign semantics and visual routing. | Migration/backfill from offers to explicit components |
| Render context always selects brand theme named `default`. | `backend/app/renderer.py:655-662` | Campaigns may need a campaign-specific theme or active theme binding. | Campaign/template binding or business active-theme reference |
| Render context only selects the first business location and orders contacts by primary flag. | `backend/app/renderer.py:664-682` | Which location/contact appears in a render is a campaign/template decision. | Campaign contact/location binding or template slot mapping |
| Effective template data only exposes merged `default_values_json` and `override_values_json`; `layout_json` and `size_spec` are not included in renderer context. | `backend/app/renderer.py:703-721`, `backend/schemas/001_init.sql:111-127` | Layout data exists in schema but the renderer cannot consume it, forcing geometry into code. | Render context: explicit `template.size_spec`, `template.layout`, `template.tokens` |
| Generated artifact file names are derived from lowercased campaign name with spaces replaced by dashes. | `backend/app/renderer.py:890-903` | Output naming may conflict with future safe path names, campaign keys, or template variants. | Artifact/output policy in campaign/template binding or output service |
| Artifact status is recorded as `complete`, while the plan refers to a richer lifecycle. | `backend/app/renderer.py:912-929`, `backend/schemas/002_artifacts.sql:1-10` | Artifact lifecycle affects operations and API behavior, not visual drawing. | Artifact pipeline schema/service |
| N-up layout uses square-ish auto grid math and repeats the same rendered flyer N times. | `backend/app/renderer.py:813-870` | N-up imposition is output-template behavior and may require gutters, crop marks, or different ordering. | Output template/imposition settings |

### A.2 Current Schema to Required Objects Gap Matrix

| Current schema/object | Current capability | Gap for data-driven rendering | Candidate Step 14b change |
|---|---|---|---|
| `template_definitions.size_spec` | Stores a string but is not passed into render context. | Page size/orientation are hardcoded to letter. | Parse and expose `size_spec`; add structured page settings if string proves too weak. |
| `template_definitions.layout_json` | Stores JSON and round-trips through YAML/API. | Renderer ignores it entirely. | Define `layout_json` schema for regions, bounds, stacking, grid policies, overflow, and visibility. |
| `template_definitions.default_values_json` | Supplies merged `effective_values` tokens. | Used for colors/text but not structured typography, region styles, or fallback policies. | Add named token groups: colors, typography, text slots, footnote policy, asset processing defaults. |
| `campaign_template_bindings.override_values_json` | Campaign-level value overrides. | Cannot override layout regions, component bindings, imposition, or output naming. | Allow structured overrides for allowed template fields or add separate binding JSON for layout/component mappings. |
| `campaign_components.component_kind` | Semantic bucket used by chat/YAML/renderer. | Renderer behavior depends directly on kind strings. | Add `render_mode` and/or `region_key`; keep `component_kind` as business/content classification if still useful. |
| `campaign_components.background_color` and `header_accent_color` | Component-level color overrides. | Only two direct color fields; no token binding, border, radius, typography, spacing, marker, or visibility controls. | Add component `style_json` or normalized component style fields after approval. |
| `campaign_components.footnote_text` | Stores component footnote copy. | Marker, placement, and overflow behavior are hardcoded. | Keep copy here; move marker/placement to template footnote policy. |
| `campaign_component_items.item_kind` | Semantic item type. | Does not express slot, render role, emphasis, row/card mode, or overflow priority. | Add `render_role`, `style_json`, or item layout hints if approved. |
| `campaign_component_items.background_color` | Item-level body fill override. | No token reference or role-specific color behavior. | Normalize color tokens or support item style JSON. |
| `campaign_offers` | Legacy flat offer data. | Missing components trigger implicit featured component creation. | Backfill explicit components/items from offers; remove render-time fallback after migration. |
| `brand_themes` | Business-level primary/secondary/accent/font/logo. | Renderer always uses theme named `default`; no active/campaign theme binding or logo processing policy. | Add active theme selection and optional asset processing metadata. |
| `business_locations` / `business_contacts` | Business profile records. | Render context selects first location and sorted contacts without template slot binding. | Add campaign/template slot binding for contact and location selection. |
| `generated_artifacts` | Stores PDF path/checksum/status. | Status enum and snapshot do not fully match planned artifact lifecycle or output variants. | Add lifecycle statuses and record N-up/output variant metadata. |
| YAML campaign `template_binding` | Round-trips template layout/default/override JSON. | No field-level contract for layout/render semantics yet. | Document and validate the new template layout schema during Step 14b. |

### A.3 Migration and Backfill Impact Summary

Existing campaigns should keep rendering as close as practical to the current PDFs after Step 14b, but the current layout is not a pixel-perfect target. Local proprietary campaign data has exposed layout limitations, and the purpose of Step 14 is to make those details configurable in the database rather than locked into renderer code. The safest migration path is to backfill explicit template and component render data that preserves current intent while allowing corrected layout details to be expressed as data.

Backfill requirements:

- Create or update the default `flyer-standard` template with structured page settings for letter size, 36 point margin, current header/featured/weekday/discount/legal/simple fallback regions, and existing rich/simple typography and spacing values.
- Populate template layout regions for `header`, `featured`, `secondary`, `discount`, `footer`, `legal`, and `campaign-footnote`, preserving the current coordinates from `backend/app/renderer.py:31-40`.
- Map existing component kinds to explicit render data:
  - `featured-offers` -> featured region, compact offer-card render mode.
  - `weekday-specials`, `other-offers`, `secondary-offers` -> secondary/weekday region, strip-list render mode.
  - `discount-strip` -> discount region, discount-panel render mode.
  - `legal-note` -> legal region, legal-text render mode.
- Preserve existing component/item color behavior by copying `background_color` and `header_accent_color` into the new style model or by making the new style model read those fields as aliases during the transition.
- Convert campaigns that have `campaign_offers` but no `campaign_components` into an explicit `offers` component with `featured-offers` compatibility data, matching the current `_fallback_components()` payload.
- Add render-context shape tests that assert the new context includes template page settings, layout regions, component bindings, render modes, style tokens, and footnote policy.
- Add visual or content snapshot baselines during Step 14b so the approved renderer behavior is protected after the data-driven refactor begins.
- Update YAML sync and write-back together with schema migration so any new template, component, item, style, and binding fields round-trip deterministically.

Implementation guidance for Step 14b:

- Prefer a practical hybrid model: keep user-facing campaign fields simple and explicit, use structured JSON for template layout/style rules that would be cumbersome to normalize immediately, and normalize only stable concepts that need direct querying, validation, or chat editing.
- Decide early in Step 14b whether `component_kind` remains as content semantics alongside `render_mode`, or whether rendering should move entirely to `region_key` and `render_mode`.
- The target user is non-technical, so schema/API complexity should be hidden behind simple YAML and editing surfaces.
- The first Step 14b visual regression test should favor stable extracted text/layout assertions plus targeted rendered-page image checks over byte-level PDF checksums, because PDF byte output can drift for reasons unrelated to user-visible rendering.
