# GPMPE — General Purpose Marketing Promotions Engine

GPMPE is a tool that helps small businesses create professional-looking marketing materials — flyers, posters, and other print-ready documents — without needing a graphic designer.

## What It Does

You describe your promotion, and GPMPE produces a polished, print-ready PDF file that you can send to a printer or share digitally. You can adjust the content through a simple chat-style interface, see a preview, and generate the final file whenever you're ready.

## How It Works

### 1. Your Business Profile
Before creating any marketing material, GPMPE needs to know about your business — things like your name, logo, brand colors, address, phone number, website, and hours of operation. This information is stored in a local SQLite database used by the running app.

### 2. Your Marketing Campaigns
Each promotion you run is stored as a campaign. A campaign holds all the details specific to that promotion — the offer, dates, pricing, imagery, and any copy you want on the flyer or poster.

Campaigns can also be structured as ordered promotion components (for example featured offers, weekday specials, discount strips, and legal notes), each with nested items. Campaigns and components support optional `footnote_text` fields used by rendering.

You can have as many campaigns as you like. If you run the same promotion in different years (for example, a Mother's Day sale), GPMPE will recognize the name and ask whether you want to work on an existing campaign or create a fresh one for the new year.

### 3. The Chat Interface
Once your business profile is set up and you've started a campaign, you work through a simple chat window. You type what you want to change — update the headline, adjust a date, swap out a discount amount — and GPMPE updates the campaign immediately. There's no complicated form to fill out.

#### Chat Context Rules

GPMPE keeps two chat contexts during an edit session:

- active campaign context
- active component context

Active campaign context:

- The active campaign is set automatically when you select a campaign in the UI.
- The active campaign is set automatically when you create a new campaign and begin editing it.
- The active campaign is set automatically when you clone a campaign and the cloned campaign becomes the current editing target.
- In backend chat handling, the active campaign is derived from the `campaign_id` sent with the chat message.
- When the active campaign changes, any previous component context is cleared automatically so stale component references do not leak across campaigns.

Active component context:

- The active component is set automatically whenever you reference a component in a successful component or component-item command.
- If you rename a component, the rename is applied first and the active component context immediately changes to the new component key.
- The active component is also set when you explicitly say something like `I am working on the weekday-specials component`, but this is optional and no longer required for normal editing.
- If you switch to a different campaign, the active component context is cleared and must be re-established by referencing a component in that campaign.

When you need to include the campaign or component name:

- You usually do not need to include the campaign name in chat because the selected campaign is already the active campaign.
- You should include the component name the first time you talk about a component in the current campaign.
- You should include the component name again after changing campaigns, because component context is reset on campaign switch.
- You should include the component name if the chatbot has not yet seen any successful component reference in the current campaign.

When you can leave the campaign or component name out:

- You can omit the campaign name for normal edits because there is only one active campaign at a time.
- You can omit the component name after a successful component reference in the current campaign.
- You can omit the component name after a component rename; follow-up item or component edits will use the renamed component automatically.

Examples:

- First component reference in a campaign:
	- `change the name of the weekday-specials component to other-services`
- Follow-up command using automatic component context:
	- `change the item_value field of the Signature Facial item to $45`
- Explicit context command when you want to set it directly:
	- `I am working on the other-services component`

If a command omits the component name before a component context has been established, GPMPE returns a clarification message instead of applying the change to the wrong component.

#### Supported Chat Commands

Commands accept short/natural field names alongside the full canonical names. The word `field` is optional, and `set`, `change`, and `update` are all accepted as the leading verb.

**Field edits — campaign**

| You can say | Canonical field |
|---|---|
| `title`, `headline`, `header` | `title` |
| `objective`, `goal` | `objective` |
| `footnote`, `note`, `footnote_text` | `footnote_text` |
| `status` | `status` |
| `start`, `starts`, `start_date` | `start_date` |
| `end`, `ends`, `end_date` | `end_date` |

Examples:
- `set headline to "Summer Savings Event"`
- `change the title to Weekend Blowout`
- `set footnote to Restrictions apply. See store for details.`
- `update status to active`

**Field edits — business profile**

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

Examples:
- `set business display name to Merci Wellness`
- `set business active to false`
- `change business city to Teaneck`

Address note: when editing address fields, GPMPE expects a complete address once any address field is present (`address_line1`, `city`, `state`, and `postal_code`).

**Field edits — brand**

| You can say | Canonical field |
|---|---|
| `primary`, `primary_color` | `primary_color` |
| `secondary`, `secondary_color` | `secondary_color` |
| `accent`, `accent_color` | `accent_color` |
| `font`, `font_family` | `font_family` |
| `logo`, `logo_path` | `logo_path` |

Examples:
- `set brand primary to #ecad0a`
- `change brand font to Georgia`

**Field edits — offer**

| You can say | Canonical field |
|---|---|
| `value`, `discount`, `amount`, `offer_value` | `offer_value` |
| `start`, `starts`, `start_date` | `start_date` |
| `end`, `ends`, `end_date` | `end_date` |
| `terms`, `terms_text` | `terms_text` |

Example: `set offer 1 discount to 20%`

**Field edits — components**

| You can say | Canonical field |
|---|---|
| `name`, `key`, `component_key` | `component_key` |
| `kind`, `type`, `component_kind` | `component_kind` |
| `title`, `display title`, `display_title` | `display_title` |
| `subtitle`, `subheading` | `subtitle` |
| `description`, `desc`, `description_text` | `description_text` |
| `footnote`, `note`, `footnote_text` | `footnote_text` |

Examples:
- `change the kind of the other-services component to legal-note`
- `change the subtitle of the other-services component to Weekday Specials`
- `change the description of the other-services component to Neighborhood appreciation offers`
- `change the footnote of the other-services component to Offers valid Monday through Thursday only`

**Field edits — component items**

| You can say | Canonical field |
|---|---|
| `value`, `price`, `cost`, `item_value` | `item_value` |
| `duration`, `duration_label` | `duration_label` |
| `description`, `desc`, `description_text` | `description_text` |
| `terms`, `terms_text` | `terms_text` |
| `name`, `item_name` | `item_name` |
| `kind`, `type`, `item_kind` | `item_kind` |

Items can be referenced by **name** or by **ordinal** (`first`, `second`, `last`, `2nd`, etc.). The component name can be omitted when an active component context is established.

Examples:
- `set the value of the Swedish Massage item to $85`
- `change the price of the second item in the main-street-appreciation component to $80`
- `change the duration of the Express Facial item to 45 min`
- `change the item_value field of the second item to $85`

**Component rename**

- `change the name of the weekday-specials component to other-services`

**Component item clone**

Clone an existing item (optionally with a new name) and insert it at a specific position:

- `clone the Swedish Massage item and add it between the Swedish Massage and the Deep Tissue items`
- `create a new item like the Swedish Massage item called Lymphatic Drainage and add it between the Swedish Massage and the Deep Tissue items`

**Component item delete**

Delete an item by ordinal or name. The component name can be omitted when an active component context is already established:

- `delete the second item in the main-street-appreciation component`
- `delete the last item in the main-street-appreciation component`
- `delete the Swedish Massage item in the main-street-appreciation component`
- `delete the Swedish Massage item` *(uses active component context)*

After deletion, GPMPE resequences the remaining items so display order stays contiguous (1, 2, 3 …).

**Component delete**

Delete an entire component and all its items. The active component context is cleared automatically:

- `delete the weekday-specials component`

**Query commands**

- `what are the components of the current promotion` — lists all components of the active campaign
- `list the components` — same
- `what are the items of the current component` — lists all items in the active component
- `list the items` — same (requires an active component to be set)

### 4. Generating the PDF
When you're happy with the content, you click to generate the PDF. GPMPE combines your business information and campaign details into a fixed, professionally formatted document and saves it to a folder on your computer. The output location is configurable, and defaults to the folder you're working in.

Optional: if `IMAGES_PER_PAGE` is set in `.config` (for example `IMAGES_PER_PAGE=4`), GPMPE also generates an additional N-up PDF for flyers. Example output names:

- `merci-may-sales.pdf` (standard single image per page)
- `merci-may-sales-4p.pdf` (4 images per page)

## Where Your Data Lives

GPMPE uses two local stores together:

- Runtime store (SQLite): configured by `DATABASE_PATH` (default `./backend/data/gpmpe.db`), used by the API and renderer.
- Repository-facing store (YAML tree): configured by `DATA_DIR`, used for import/sync and write-back.

On startup, GPMPE initializes schema and syncs YAML from `DATA_DIR` into SQLite. The YAML directory follows this structure:

- one business directory per business
- one business YAML file named after the business directory
- one campaign directory per campaign under the business
- one campaign YAML file named after the campaign directory

This keeps campaign data portable and versionable while maintaining a fast runtime database for API and rendering.

Important: in MVP, startup sync is authoritative for YAML-managed records and removes stale DB records that are no longer present in the YAML tree.

## Test Output

Test-generated artifacts should stay in ignored directories.

- Backend pytest temporary files are written under `.test-output/backend/pytest/`.
- Backend pytest temporary files are written under `.test-output/pytest/`.
- Frontend Vite/Vitest cache and coverage output are written under `.test-output/frontend/`.
- Ad hoc reports and future test artifacts should prefer subdirectories under `.test-output/`.

## Test Path Overrides

You can keep both runtime and test storage settings in the same `.config` file.

- `DATABASE_PATH` and `DATA_DIR` remain the normal runtime paths.
- `TEST_DATABASE_PATH` and `TEST_DATA_DIR` define an isolated test SQLite file and isolated YAML data tree.
- GPMPE only switches to the test paths when both test settings are present and test-path mode is enabled.
- Enable test-path mode by setting `GPMPE_USE_TEST_PATHS=true` for the test process.
- If test-path mode is enabled but either `TEST_DATABASE_PATH` or `TEST_DATA_DIR` is missing, config resolution fails instead of mixing runtime and test state.

## Key Concepts at a Glance

| Term | What It Means |
|------|---------------|
| Business Profile | Your permanent business information — name, logo, branding, contact details |
| Campaign | A single marketing promotion with its own offer, dates, and content |
| Secondary Key | An optional label (like a year) that distinguishes two campaigns with the same name |
| PDF Output | The final print-ready file produced from your campaign |
| Output Directory | The folder on your computer where generated PDFs are saved |

## What GPMPE Is Not

- It is not a design tool. Layouts and formatting are handled by the application using predefined templates.
- It is not an AI writing assistant. You provide the content; GPMPE formats and arranges it.
- It is not a cloud service. Everything runs locally on your machine or in a container you control.

## Container Runtime (Step 8)

You can build and run GPMPE in a single Docker container that serves both:

- backend API (FastAPI)
- frontend static app (Next.js export output)

### Build

From the repository root:

```bash
docker build -t gpmpe:local .
```

### Run

The container can read storage paths from `.config` or from environment variables. Environment variables take precedence, which is the recommended pattern for Docker and AWS/EFS deployments.

```bash
docker run --rm -p 8000:8000 \
	-v "$PWD/.config:/app/.config:ro" \
	-v "$PWD/data:/app/data" \
	-v "$PWD/output:/app/output" \
	-e DATA_DIR=/app/data \
	-e OUTPUT_DIR=/app/output \
	gpmpe:local
```

Then open:

- `http://127.0.0.1:8000/` for the frontend
- `http://127.0.0.1:8000/health` for backend health

## Migration Parity Workflow (Step 9)

To validate refactor parity against a proprietary reference PDF, use local-only files
outside git-tracked content and run the parity helper script.

Example:

```bash
.venv/bin/python backend/scripts/local_parity_check.py \
	output/your-generated.pdf \
	/absolute/path/to/your/reference.pdf
```

Notes:

- Keep proprietary reference files under ignored local paths only.
- Do not commit proprietary PDFs, assets, or notes to this repository.
- A non-zero exit code indicates mismatch and should block migration sign-off.

## One-Line Startup (Step 10)

### Docker (recommended)

From a clean clone (with `.config` present):

```bash
docker compose up
```

This builds and runs a single container that serves both API and frontend on `http://127.0.0.1:8000`.

Before running, make sure `.config` contains valid `DATA_DIR`, `DATABASE_PATH`, and `OUTPUT_DIR` values for your local machine.
Set `IMAGES_PER_PAGE` only if you want the extra N-up PDF output.

The compose file mounts:

- `.config` as container runtime config
- `output/` for generated artifacts
- `backend/data/` for SQLite persistence
- `local/` and `data/` for YAML-backed campaign data

### Local Script

For non-Docker local startup:

```bash
./start.sh
```

To stop local services started via scripts/tasks:

```bash
./stop.sh
```

The script:

- builds the frontend static export
- copies static output into `backend/app/static/`
- starts uvicorn
- waits for `/health` readiness before reporting success

The stop script:

- stops backend listening on `PORT` (default `8000`)
- stops frontend listening on `FRONTEND_PORT` (default `3100`)
- escalates to force-stop if graceful shutdown does not complete in time
