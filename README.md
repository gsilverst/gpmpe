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

The container expects a `.config` file with at least `DATA_DIR` and a writable `OUTPUT_DIR`.

```bash
docker run --rm -p 8000:8000 \
	-v "$PWD/.config:/app/.config:ro" \
	-v "$PWD/data:/app/data" \
	-v "$PWD/output:/app/output" \
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

The script:

- builds the frontend static export
- copies static output into `backend/app/static/`
- starts uvicorn
- waits for `/health` readiness before reporting success
