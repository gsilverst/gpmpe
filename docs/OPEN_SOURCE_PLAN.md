# Open Source Plan

This plan captures the work needed to make GPMPE ready for a public open source release.

GPMPE is an AWS-oriented application for building print-ready marketing promotion flyers through a chat-first campaign workflow. The product is intended for management, marketing, and other non-technical business users who should be able to create and evolve campaigns from scratch through the chatbot interface, without editing YAML or writing code. The target production architecture uses AWS-managed services, especially Amazon RDS for the runtime database, while preserving a local SQLite/filesystem mode for development, demos, and fallback operation. The open source release should make the user-facing product promise, the chat-first workflow, and the dual-mode architecture obvious, while protecting private/local data and giving contributors a clear path to run, test, deploy, and improve the project.

## Goals

- Publish GPMPE as a usable, AWS-oriented marketing promotions engine.
- Emphasize chat-first campaign creation for management, marketing, and non-technical business users.
- Support building campaigns completely from scratch through the chatbot interface.
- Preserve a local SQLite option for development, demos, testing, and lightweight single-machine use.
- Make the first-run experience straightforward for developers and technically curious users.
- Keep private client data, generated artifacts, API keys, local databases, and machine-specific configuration out of the public repository.
- Establish basic project governance so contributors know how to participate.
- Add enough CI coverage to catch obvious backend/frontend regressions in local mode, with a path toward AWS staging verification.

## Positioning

Recommended project description:

> GPMPE is an AWS-oriented, chat-first marketing promotions engine that helps management and marketing teams create print-ready campaign flyers from scratch, with Amazon RDS for production deployments and SQLite for local development.

Product stance:

- The primary user experience is the chatbot interface.
- Management, marketing, and other non-technical users are the primary end users.
- Users should be able to build a campaign completely from scratch through chat.
- Users should also be able to evolve existing campaigns through chat, including changes to headlines, offers, dates, services, pricing, sections, and terms.
- YAML remains valuable as a portable storage and version-control representation, but direct YAML editing should not be required for normal campaign work.

Architecture stance:

- AWS production is the target deployment model.
- Amazon RDS is the intended production runtime database.
- Amazon EFS is the planned cloud filesystem layer for YAML data and generated output parity.
- SQLite remains the local development, test, demo, and fallback database.
- The same codebase should support both modes through configuration.
- YAML campaign data remains important for portability and version control, with cloud sync planned through a Git-to-EFS worker.

Primary audience:

- Management and marketing teams who need to create and revise campaign flyers without design tools or code.
- Small business operators and agency account teams who want to build promotions conversationally.
- Business stakeholders who prefer describing campaign changes in natural language through the chatbot interface.
- Developers, agencies, and contributors deploying or extending the AWS/RDS-backed application for those non-technical users.

The public README should make clear that GPMPE is early-stage software, that the AWS migration is in progress, and that the initial release supports local development while the production architecture is moving toward RDS/EFS-backed AWS deployment.

## License Decision

Choose a license before publishing.

Recommended license: Apache-2.0.

Rationale:

- It is business-friendly.
- It is widely understood by companies and contributors.
- It includes explicit patent language, which is stronger than MIT for long-term project safety.

Alternatives:

- MIT: simpler and very permissive, but less explicit about patents.
- AGPL-3.0: useful if the goal is to require hosted derivatives to share source changes, but it may reduce commercial adoption.

Action items:

- Add a root `LICENSE` file.
- Mention the license in `README.md`.
- Confirm third-party dependency licenses are compatible with the chosen license.

## Data And Privacy Cleanup

Before making the repository public, review all tracked and publishable files for private, proprietary, or client-specific data.

Current guidance:

- Keep generic demo data, such as `data/solara-wellness`, if it is fictional and safe to publish.
- Do not publish sibling project data such as `../private_customer_data` unless explicit permission exists and the data has been scrubbed.
- Do not publish local/generated outputs, SQLite databases, API keys, personal paths, or proprietary reference PDFs.
- Publish `.config.example`, not `.config`.

Review these areas carefully:

- `data/`
- `local/`
- `output/`
- `backend/data/`
- `testdb/`
- `README.pdf`
- `PLAN.pdf`
- Any generated campaign PDFs
- Any files containing real business names, phone numbers, addresses, logos, API keys, or customer-specific copy

Existing `.gitignore` coverage already includes many important local artifacts:

- `.config`
- `.env`
- `.venv/`
- `node_modules/`
- `output/`
- `frontend/out/`
- `backend/data/`
- `testdb/`
- `*.db`
- `*.log`

Action items:

- Run `git status --ignored` and confirm sensitive files are ignored.
- Remove or move any tracked proprietary PDFs or client-specific assets.
- Keep only safe sample data in the public repo.
- Add notes to the README explaining that campaign data is local and user-owned.

## Governance Files

Add standard open source project files at the repository root.

Required:

- `LICENSE`
- `CONTRIBUTING.md`
- `CODE_OF_CONDUCT.md`
- `SECURITY.md`
- `CHANGELOG.md`

Recommended GitHub metadata:

- `.github/ISSUE_TEMPLATE/bug_report.yml`
- `.github/ISSUE_TEMPLATE/feature_request.yml`
- `.github/pull_request_template.md`

Suggested contents:

- `CONTRIBUTING.md`: local setup, test commands, coding style, pull request expectations, data privacy rules.
- `CODE_OF_CONDUCT.md`: Contributor Covenant or a similarly standard, concise policy.
- `SECURITY.md`: supported versions, vulnerability reporting contact, API key and local-data handling expectations.
- `CHANGELOG.md`: start with `Unreleased` and prepare for `v0.1.0`.

## README Improvements

The README is already detailed, but the public version should start with a stronger open source landing section.

Recommended top-level structure:

- What GPMPE is
- Who it is for: management, marketing, and non-technical campaign owners
- Chat-first campaign creation
- Architecture status: AWS production target plus local SQLite mode
- Screenshot or sample generated flyer
- Current status
- Features
- AWS deployment roadmap
- Quickstart with Docker
- Quickstart with local Python/Node
- Data model and YAML layout
- Generating a flyer
- Configuration
- Testing
- Contributing
- License

Action items:

- Add a concise opening summary.
- State that the chatbot is the preferred campaign-building interface.
- Explain that campaigns can be created from scratch through chat.
- Show a short example chat flow that creates or evolves a campaign.
- Add a clear “Status: early MVP; AWS migration in progress” note.
- Link to `docs/AWS_MIGRATION_PLAN.md`.
- Explain the dual-build structure: local SQLite/filesystem mode and AWS RDS/EFS mode.
- Add a short Docker quickstart near the top.
- Add a local development quickstart near the top.
- Add a safe sample-data walkthrough.
- Link to detailed docs in `docs/`.
- Move long command-reference sections lower or into dedicated docs if the README becomes too dense.

## First-Run Experience

The project should be easy to run from a clean clone while making the production deployment direction clear.

Target flows:

- End-user demo flow: start with sample data, use the chatbot to create or modify a campaign, then generate a flyer.
- Local Docker: one command starts the app with demo data using SQLite/filesystem storage.
- Local Python/Node: documented Python virtualenv plus frontend install/build commands using SQLite/filesystem storage.
- Project mode: documented `start-project.sh` flow for using GPMPE against a sibling data project.
- AWS mode: documented target architecture using RDS for runtime data and EFS for YAML/output storage, with deployment details tracked in `docs/AWS_MIGRATION_PLAN.md`.

Action items:

- Verify `.config.example` is complete and safe.
- Document copying `.config.example` to `.config`.
- Add a first-run walkthrough centered on the chatbot workflow.
- Include a from-scratch campaign creation example using only chat commands.
- Confirm `docker compose up` works from a clean checkout.
- Confirm `./start.sh` works from a clean checkout after dependencies are installed.
- Confirm generated artifacts land in `output/`.
- Document planned `DATABASE_URL`/RDS configuration once the SQLAlchemy migration lands.
- Document planned `RUN_MODE=local|aws` behavior once the AWS migration lands.
- Add troubleshooting notes for missing Node, missing Python environment, port conflicts, and stale generated files.

## CI Plan

Add GitHub Actions before public release.

Minimum CI checks:

- Backend tests with `pytest` using SQLite/local mode.
- Frontend dependency install with `npm ci`.
- Frontend tests or build, depending on current package scripts.

Recommended workflow file:

- `.github/workflows/ci.yml`

Suggested jobs:

- `backend-tests`
- `frontend-tests`
- Optional later: `docker-build`
- Optional later: `aws-staging-parity`

Action items:

- Confirm backend test command from a clean checkout.
- Confirm frontend test/build command from a clean checkout.
- Add caching for Python and npm dependencies if useful.
- Ensure CI uses test paths and does not depend on private local data.
- After the AWS migration lands, add staging verification against RDS in a protected AWS environment.

## Security, AWS, And LLM Configuration

GPMPE includes local configuration, planned AWS-managed configuration, and optional LLM integration. Public docs should make the boundaries explicit.

Action items:

- Document that local mode stores user data on the local filesystem and in SQLite.
- Document that AWS mode is intended to store runtime data in RDS and YAML/output files on EFS.
- Document that AWS production secrets should live in AWS Secrets Manager or Parameter Store.
- Document `OPENROUTER_API_KEY` handling.
- Confirm no API keys or real secrets are committed.
- Confirm `.env` and `.config` remain ignored.
- Add `SECURITY.md` with vulnerability reporting instructions.
- Explain that users should not commit generated PDFs, client data, local SQLite databases, AWS credentials, or deployment secrets unless intentionally publishing safe sample data.

## Release Strategy

Recommended first public release: `v0.1.0`.

Before tagging:

- Complete data cleanup.
- Add governance files.
- Add CI.
- Update README.
- Confirm demo data works.
- Run backend and frontend tests.
- Generate a sample flyer from demo data.
- Create a GitHub release with known limitations.

Suggested release notes:

- Chat-first campaign creation for management, marketing, and non-technical users.
- Campaigns can be built from scratch and evolved through the chatbot interface.
- AWS-oriented architecture with local SQLite development support.
- Campaign data stored as YAML plus a runtime database.
- PDF flyer rendering.
- Optional 4-up flyer output with `IMAGES_PER_PAGE`.
- Chat-based campaign editing commands.
- Demo campaign data.
- Known limitations and AWS migration roadmap.

## Pre-Publication Checklist

- [ ] Choose license.
- [ ] Add `LICENSE`.
- [ ] Add `CONTRIBUTING.md`.
- [ ] Add `CODE_OF_CONDUCT.md`.
- [ ] Add `SECURITY.md`.
- [ ] Add `CHANGELOG.md`.
- [ ] Add GitHub issue and pull request templates.
- [ ] Review tracked files for private data.
- [ ] Remove or move proprietary PDFs and real client assets.
- [ ] Keep only safe fictional/demo data.
- [ ] Confirm `.config`, `.env`, DBs, generated PDFs, and outputs are ignored.
- [ ] Update README for public onboarding.
- [ ] Document the non-technical management/marketing user audience.
- [ ] Document chatbot-first campaign creation.
- [ ] Add a from-scratch chat campaign example.
- [ ] Link README to `docs/AWS_MIGRATION_PLAN.md`.
- [ ] Document AWS production target and local SQLite development mode.
- [ ] Verify Docker quickstart.
- [ ] Verify local quickstart.
- [ ] Add GitHub Actions CI.
- [ ] Run backend tests.
- [ ] Run frontend tests/build.
- [ ] Generate a demo flyer.
- [ ] Tag `v0.1.0`.
- [ ] Publish GitHub release notes.

## Suggested First Open Source PR

Create one focused readiness PR before making the repository public.

Scope:

- Add Apache-2.0 `LICENSE`.
- Add governance files.
- Add GitHub templates.
- Add basic CI.
- Update README opening and quickstart.
- Add AWS/RDS production positioning and link to migration plan.
- Confirm sample data is safe.
- Document privacy, local-data, and AWS secret-management expectations.

Avoid in this PR:

- Major rendering refactors.
- New product features.
- Client-specific campaign additions.
- Large UI redesigns.

The goal is to make the project safe, understandable, and contributor-ready without changing its core behavior.
