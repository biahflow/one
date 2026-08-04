# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Portal Labs — a multi-tenant client portal where customers track AI project progress, results, and decisions, with a context-aware assistant that answers **only** with evidence from the project (citations, never invention). Product docs are PT-BR; code, API, and DB identifiers are English.

The repo is a monorepo currently at the "foundation" stage: the web dashboard and API endpoints exist as **demo/prototype** surfaces (hardcoded data, `DEMO_MODE`), while real auth, tenancy, RAG, and persistence are still on the roadmap. See `ROADMAP.md` for what is built vs. planned. When changing behavior, check whether the code you're touching is a demo placeholder or a real implementation.

## Architecture

Three deployables (`docs/architecture.md`):

```
Browser → Next.js BFF → FastAPI → PostgreSQL + pgvector
                         ├→ Redis/Celery → Drive, email, indexing
                         └→ MinIO/S3 → documents & transcripts
```

- **`app/`** — the web frontend: stock **Next.js 16** (App Router, React 19 RSC) served by `next start` on Node, containerized like every other service (ADR 0009). `app/page.tsx` is the server component: it fetches `GET /api/v1/me/dashboard` in `loadOverview()` and falls back to `DEMO_OVERVIEW` when the API is unreachable; `app/DashboardClient.tsx` is the `"use client"` UI that renders that `Overview` (`answerFor()` is only the offline chat fallback). The frontend's role is BFF: it never decides authorization.
- **`apps/api/`** — FastAPI (`portal_api`), Python 3.13, Pydantic settings. `main.py` holds the REST contracts under `/api/v1`; several endpoints are contract stubs that only work when `DEMO_MODE=true` and otherwise 401/404 until the auth/RLS migration lands.
- **`apps/api/src/portal_api/{db,models,repositories}/`** — the Postgres data layer (SQLAlchemy 2.0 + Alembic). Models live in the `portal` schema, but the metadata is **not** schema-qualified: the engine pins the connection `search_path` to `portal` (`db/session.py`) so DDL and reflection stay unqualified and `alembic check` sees no false drift — keep new models unqualified too. `db/base.py` provides `TenantMixin` (adds `organization_id`; project tables also add `project_id`). Data access goes through `repositories/`: `TenantScopedRepository` filters every read and stamps every write from a `TenantContext`, enforcing org/project isolation at the app layer (the barrier before RLS). Tenant roots (organization, user) use the plain `Repository`.
- **`apps/api/src/portal_api/worker.py`** — Celery worker for async jobs (Drive/document ingestion), gated on Redis.

There is exactly one data layer: the FastAPI service owns PostgreSQL+pgvector (source of truth, planned RLS per org/project). The web layer is stateless — it holds no database of its own.

## Styling

Tailwind CSS v4, configured entirely in `app/globals.css` (no `tailwind.config.js`). The `@theme` block is the single source of design tokens — brand scale (`brand-50…900`, the Portal Labs purple), `ink`/`muted`/`line`/`canvas`/`navy`, state colors and the layered shadows. Recurring UI (`.panel`, `.nav-item`, `.milestone`, `.journey-*`, …) lives in `@layer components` built from Tailwind utilities via `@apply`, so the markup stays readable and the tokens stay authoritative; the three responsive breakpoints (761px collapsed sidebar, 980px, 760px mobile) are plain media queries at the end of the file. Never hardcode a hex in a component — add or use a token.

## Non-negotiable rules (from `AGENTS.md`)

1. Every datum belongs to an organization **and** a project. Never trust a client-supplied identifier without server-side validation of the membership link.
2. Never send secrets, tokens, system prompts, or another project's context to the AI model.
3. AI answers must cite sources. With no evidence, declare the gap and create a pending item (`pendência`) — never invent an answer.
4. Migrations are additive and reviewed. Changes to tenancy, auth, RAG, or retention require an ADR/RFC (`docs/adr/`, `docs/rfc/`).
5. Backend validates identity, org, project, and role — the frontend does not decide authorization.
6. Add a negative-permission test case for any new endpoint or search.

## Commands

Web (Node ≥ 22.13):
```bash
npm run dev      # next dev
npm run build    # next build → .next/
npm test         # builds, then runs tests/rendered-html.test.mjs (node --test)
npm run lint     # eslint
```

`npm test` **requires a build first**: the test boots `next start` on a random port and fetches it, so the script chains `npm run build && node --test`. To run the web tests alone after a build: `node --test tests/rendered-html.test.mjs`.

API (Python 3.13):
```bash
pip install -r apps/api/requirements-dev.txt
PYTHONPATH=apps/api/src pytest apps/api/tests            # all API tests
PYTHONPATH=apps/api/src pytest apps/api/tests/test_main.py::test_health_is_available   # single test
```

`test_main.py` demo endpoints need `DEMO_MODE=true`. The data-layer tests are marked `integration` and need a reachable Postgres via `DATABASE_URL` — they **self-skip** when it is absent (so a bare `pytest` still passes), and `tests/conftest.py` runs `alembic upgrade head` before they run. To exercise them: `docker compose up -d postgres`, then run pytest with `DATABASE_URL=postgresql+psycopg://portal:portal_local_only@localhost:5432/portal`.

Migrations (Alembic, from `apps/api/`, with `DATABASE_URL` set):
```bash
PYTHONPATH=src alembic upgrade head        # apply
PYTHONPATH=src alembic check               # fail if models drift from migrations
PYTHONPATH=src alembic revision --autogenerate -m "<msg>"
```

Full local platform (web, API, worker, Postgres+pgvector, Redis, MinIO, Keycloak, Mailpit):
```bash
cp .env.example .env
docker compose up --build
```
Endpoints: web `:3000`, API/OpenAPI `:8000/docs`, Keycloak `:8080`, MinIO console `:9001`, Mailpit `:8025`.

CI (`.github/workflows/ci.yml`) runs four gates you should reproduce locally before a PR: `web-quality` (lint + test), `api-quality` (pytest), `local-stack` (`docker compose config --quiet` + `docker compose build`), plus dependency-review and CodeQL.

## Conventions

- REST under `/api/v1`; Pydantic payloads and standardized errors.
- Web tests assert against **server-rendered HTML** (`tests/rendered-html.test.mjs` boots `next start` and matches strings like the page title and dashboard copy). If you change dashboard text/structure, update these assertions. The second test scans every source file under `app/` and `components/` to guard against reintroducing hardcoded tab data (the Fase 2 regression) and starter leftovers.
- API demo endpoints branch on `settings.demo_mode`; keep that gate when adding contract stubs that lack real auth.
- Every feature ships with an FDD (`docs/fdd/`) carrying acceptance criteria, telemetry, tests, and AI eval cases; prompt/retriever/model/tool changes require AI evals (`docs/ai/`).
