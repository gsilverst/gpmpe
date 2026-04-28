# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# Project Overview

GPMPE is a general purpose marketing promotions engine for small businesses to generate flyers, posters, and other marketing material in the form of pdfs. The app is deployed as a single Docker container serving both static frontend assets and the API. The goal is to refactor an existing proprietary single-promotion flyer generator into a general purpose engine that can implement arbitrary marketing promotions with all business specific information (logo, branding, colors, address, phone number, email, website, hours, etc.) stored in the database along with any information related to the promotion itself.

## Architecture

### Stack
- **Frontend:** Next.js (App Router), React, TypeScript, Tailwind CSS v4, dnd-kit for drag-and-drop
- **Backend:** Python 3.12, FastAPI, SQLite (auto-created at `backend/data/gpmpe.db`)
- **AI:** OpenRouter API (`openai/gpt-oss-120b`) via `OPENROUTER_API_KEY` in `.env`


### Data Model 

Data model should consist of at least two objects representing the business information and a campaign object representing the marketing promotion that will be used to create the pdf for the flyer and/or poster. Both of these objects should be stored in a database and should be used by the AI to generate marketing material.

The schemas for all objects should be store in a subdirectory called schemas along with any other information needed to setup the database. For now the data will be stored in a SQLite database in the backend directory. However the eventual goal is to store the data in an SQL database under AWS (most likely RDS). Please keep that in mind as you design the data model.

Any proprietary business or promotion data used during development must remain in local-only ignored files and must not be stored in git-tracked repository content.

### Docker Multi-stage Build (`Dockerfile`)
1. **Stage 1 (node:22-alpine):** Installs frontend deps, runs `npm run build`, produces `out/`
2. **Stage 2 (python:3.12-slim):** Installs `uv`, copies `out/` to `backend/app/static/`, runs uvicorn

## Testing Notes

- **Frontend e2e dev mode** uses port 3100 (configured in `playwright.config.ts`), not 3000
- **Backend pytest** uses `TestClient` — tests share a fresh in-memory SQLite DB per test session
- Playwright e2e tests skip persistence assertions when running against dev server (no backend)

## Design Tokens

Defined as CSS variables in `frontend/src/app/globals.css`:
- Accent yellow: `#ecad0a`
- Blue primary: `#209dd7`
- Purple secondary: `#753991`
- Dark navy: `#032147`

## Conventions (from AGENTS.md)

- Keep it simple — no over-engineering, no unnecessary defensive programming
- No CI/CD — local Docker runtime only
- Use `uv` for Python package management (not pip directly)
