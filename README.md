# GPMPG — General Purpose Marketing Promotions Generator

GPMPG is a tool that helps small businesses create professional-looking marketing materials — flyers, posters, and other print-ready documents — without needing a graphic designer.

## What It Does

You describe your promotion, and GPMPG produces a polished, print-ready PDF file that you can send to a printer or share digitally. You can adjust the content through a simple chat-style interface, see a preview, and generate the final file whenever you're ready.

## How It Works

### 1. Your Business Profile
Before creating any marketing material, GPMPG needs to know about your business — things like your name, logo, brand colors, address, phone number, website, and hours of operation. This information is stored in a database that belongs entirely to your business. It is kept separate from the application itself, so your data stays yours and is never mixed with another business's information.

### 2. Your Marketing Campaigns
Each promotion you run is stored as a campaign. A campaign holds all the details specific to that promotion — the offer, dates, pricing, imagery, and any copy you want on the flyer or poster.

You can have as many campaigns as you like. If you run the same promotion in different years (for example, a Mother's Day sale), GPMPG will recognize the name and ask whether you want to work on an existing campaign or create a fresh one for the new year.

### 3. The Chat Interface
Once your business profile is set up and you've started a campaign, you work through a simple chat window. You type what you want to change — update the headline, adjust a date, swap out a discount amount — and GPMPG updates the campaign immediately. There's no complicated form to fill out.

### 4. Generating the PDF
When you're happy with the content, you click to generate the PDF. GPMPG combines your business information and campaign details into a fixed, professionally formatted document and saves it to a folder on your computer. The output location is configurable, and defaults to the folder you're working in.

## Where Your Data Lives

All information about your business and your campaigns is stored in a database that is specific to your business. This database lives outside the GPMPG application itself — in a separate repository that you control. This means:

- Your data is portable. You can move it, back it up, and version-control it independently of the application.
- Different businesses using GPMPG each have their own isolated database. There is no shared data store.
- The application only reads and writes to your database when you are actively working on your materials.

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
- GPMPG only switches to the test paths when both test settings are present and test-path mode is enabled.
- Enable test-path mode by setting `GPMPG_USE_TEST_PATHS=true` for the test process.
- If test-path mode is enabled but either `TEST_DATABASE_PATH` or `TEST_DATA_DIR` is missing, config resolution fails instead of mixing runtime and test state.

## Key Concepts at a Glance

| Term | What It Means |
|------|---------------|
| Business Profile | Your permanent business information — name, logo, branding, contact details |
| Campaign | A single marketing promotion with its own offer, dates, and content |
| Secondary Key | An optional label (like a year) that distinguishes two campaigns with the same name |
| PDF Output | The final print-ready file produced from your campaign |
| Output Directory | The folder on your computer where generated PDFs are saved |

## What GPMPG Is Not

- It is not a design tool. Layouts and formatting are handled by the application using predefined templates.
- It is not an AI writing assistant. You provide the content; GPMPG formats and arranges it.
- It is not a cloud service. Everything runs locally on your machine or in a container you control.
