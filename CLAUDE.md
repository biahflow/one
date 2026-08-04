# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Portal Labs — a multi-tenant client portal where customers track AI project progress, results, and decisions, with a context-aware assistant that answers **only** with evidence from the project (citations, never invention). Product docs are PT-BR; code, API, and DB identifiers are English.

The repo is a monorepo, and Fase 1 (identity, roles, RLS) is complete on both halves. **The API** validates the OIDC access token, authorizes from the `membership` and enforces Row-Level Security (ADR 0010) — every client endpoint requires `Authorization: Bearer` and answers 404, never 403, on a denial. **The web layer** is a real OIDC client: Auth.js v5 does the code exchange server-side, `proxy.ts` closes everything but `/login`, and `app/page.tsx` renders from the API. There is no fallback to fabricated data any more — 401 goes to `/login`, 404 says "no project assigned", a network failure is an error panel. What is still open: invitation/e-mail verification, the admin UI, and RAG (`ROADMAP.md`).

## Architecture

Three deployables (`docs/architecture.md`):

```
Browser → Next.js BFF → FastAPI → PostgreSQL + pgvector
                         ├→ Redis/Celery → Drive, email, indexing
                         └→ MinIO/S3 → documents & transcripts
```

- **`app/` (+ `auth.ts`, `proxy.ts` at the root)** — the web frontend: stock **Next.js 16** (App Router, React 19 RSC) served by `next start` on Node, containerized like every other service (ADR 0009). `auth.ts` configures Auth.js v5 with the confidential Keycloak client; `proxy.ts` (Next 16's name for the middleware) is the session gate — a redirect for pages, a 401 for `/api/`. `app/page.tsx` is the server component: it fetches `GET /api/v1/me` and the dashboard in parallel with the token from `app/lib/session.ts`, and projects both into the props of `app/DashboardClient.tsx`, the `"use client"` UI (`answerFor()` is only the offline chat fallback). The frontend's role is BFF: it never decides authorization.
- **`apps/api/`** — FastAPI (`portal_api`), Python 3.13, Pydantic settings. `main.py` holds the REST contracts under `/api/v1`. Every client endpoint depends on `CurrentPrincipal` (`auth.py`), which validates the OIDC access token against the realm's JWKS; `identity.py` turns that principal into a `user` row (link by e-mail on first login, provision if unknown) and `access.py` decides what the user reaches — always `None` → 404, never 403.
- **`apps/api/src/portal_api/{db,models,repositories}/`** — the Postgres data layer (SQLAlchemy 2.0 + Alembic). Models live in the `portal` schema, but the metadata is **not** schema-qualified: the engine pins the connection `search_path` to `portal` (`db/session.py`) so DDL and reflection stay unqualified and `alembic check` sees no false drift — keep new models unqualified too. `db/base.py` provides `TenantMixin` (adds `organization_id`; project tables also add `project_id`). Data access goes through `repositories/`: `TenantScopedRepository` filters every read and stamps every write from a `TenantContext`, enforcing org/project isolation at the app layer — the barrier *before* RLS, which is the second one below it.

## Tenancy and the database roles (ADR 0010)

Three credentials, one per kind of work, and `DATABASE_URL` is the request path:

| Setting | Role | RLS |
|---|---|---|
| `DATABASE_URL` | `portal_app` — API and worker request path | **subject to it** |
| `DATABASE_SYSTEM_URL` | `portal_system` — Biahflow webhook, sync, seed | `BYPASSRLS` |
| `DATABASE_MIGRATION_URL` | `portal_migrator` — owns the schema, runs Alembic | exempt as owner |

`get_session(principal)` publishes the tenant context as transaction-local GUCs, in two stages: identity (`portal.subject`, `portal.email`, `portal.user_id`) and tenant (`portal.organization_id`, `portal.project_id`). The policies read those, and `current_setting(..., true)` returns NULL when unset — so **missing context yields zero rows, never an unscoped read**. `access.scoped_project`/`default_project` call `bind_tenant` themselves; if you add a resolver that returns a project, it must do the same or every later read comes back empty (`docs/runbooks/auth-failure.md`).

**Every new table carrying `organization_id` ships with a policy in the same migration.** A meta-test in `test_rls_isolation.py` fails CI otherwise. The app role holds `SELECT` almost everywhere, `INSERT` only on `pending_item` and `audit_log`, and `INSERT/UPDATE` on `user` — mirroring "the portal never originates status" (ADR 0006/0008) in the database itself.
- **`apps/api/src/portal_api/worker.py`** — Celery worker for async jobs (Drive/document ingestion), gated on Redis.
- **`apps/api/src/portal_api/seed.py`** — the local seed, run by the `api-seed` compose service. Its `SEED_USERS` carry the same UUIDs the realm import fixes as user ids, which *are* the `sub` claim, so a seeded row already knows its `external_subject`. `test_seed_matches_realm.py` fails the build if the two drift. The project data enters through `sync_snapshot()` with a versioned snapshot — the webhook's own door, so the portal still originates no status (ADR 0006/0008).

There is exactly one data layer: the FastAPI service owns PostgreSQL+pgvector (source of truth, RLS per org/project). The web layer is stateless — it holds no database of its own.

## The session (ADR 0010)

The BFF is a **confidential** OIDC client. The authorization code is exchanged on the server and the access token is stored in the encrypted Auth.js cookie — never in the `session` object, so it cannot reach a client bundle or an RSC payload. `app/lib/session.ts` is the only way to read it back; a new server-side call to the API takes its `Authorization` header from `authorizationHeader()`.

**Two URLs for one Keycloak, and they are not a mistake.** The browser reaches it at `KEYCLOAK_ISSUER` (`localhost:8080`), and that address is the `iss` of every token, which is what the API validates against `OIDC_ISSUER`. The containers reach it at `KEYCLOAK_INTERNAL_URL` (`keycloak:8080`), which is where the token exchange and the refresh go. `auth.ts` passes both endpoints explicitly, which also skips OIDC discovery — discovery would refuse the mismatch. The API mirrors the split with `OIDC_ISSUER`/`OIDC_JWKS_URL`.

Roles are deliberately **absent** from the session: a realm role cannot say *which project*, so the UI reads them from `GET /api/v1/me`, which answers from the membership.

Demo data has exactly one door left, `demoShellEnabled()` in `app/lib/demo.ts`: no `API_BASE_URL` **and** `DEMO_MODE=true`. It is the only exception in `proxy.ts`, and a test asserts that `DEMO_OVERVIEW` is unreachable outside that gate. Do not widen it.

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
npm run test:e2e # playwright, against a running `docker compose up`
npm run lint     # eslint
```

`npm test` **requires a build first**: the test boots `next start` on a random port and fetches it, so the script chains `npm run build && node --test`. To run the web tests alone after a build: `node --test tests/rendered-html.test.mjs`. It needs no Keycloak and no API — it forges the session cookie with Auth.js' own `encode()` and serves the API from a `node:http` stub.

`npm run test:e2e` is the opposite: it needs the whole stack up (`docker compose up -d`) because it drives a real browser through the real realm. `npx playwright install chromium` once, first.

API (Python 3.13):
```bash
pip install -r apps/api/requirements-dev.txt
PYTHONPATH=apps/api/src pytest apps/api/tests            # all API tests
PYTHONPATH=apps/api/src pytest apps/api/tests/test_main.py::test_health_is_available   # single test
```

`python -m portal_api.seed` applies the local seed (the `api-seed` service does it on every `up`); it is idempotent and needs `DATABASE_SYSTEM_URL`. `test_main.py` demo endpoints need `DEMO_MODE=true`. The data-layer tests are marked `integration` and need a reachable Postgres — they **self-skip** when there is none (so a bare `pytest` still passes), and `tests/conftest.py` runs `alembic upgrade head` first. To exercise them: `docker compose up -d postgres db-bootstrap` (the bootstrap creates the three roles; without it the RLS tests would run as the owner and pass without proving anything). The defaults in `config.py` already point at that local stack.

Three session fixtures, one per role: `db_session` (`portal_system`, arranges data across tenants), `rls_session` (`portal_app`, the only way to observe the policies), `migrated_engine` (`portal_migrator`). A test that asserts isolation must use `rls_session` or the HTTP client — `db_session` bypasses RLS by design.

Migrations (Alembic, from `apps/api/`, with `DATABASE_MIGRATION_URL` set):
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

CI (`.github/workflows/ci.yml`) runs four gates you should reproduce locally before a PR: `web-quality` (lint + test), `api-quality` (pytest), `local-stack` (`docker compose config --quiet` + `docker compose build`), plus dependency-review and CodeQL. A fifth job, `e2e-login`, boots the stack and runs Playwright; it is `continue-on-error` for now, so read it rather than trust the green.

## Conventions

- REST under `/api/v1`; Pydantic payloads and standardized errors.
- Web tests assert against **server-rendered HTML** (`tests/rendered-html.test.mjs` boots `next start` and matches strings like the page title and dashboard copy). If you change dashboard text/structure, update these assertions. The second test scans every source file under `app/` and `components/` to guard against reintroducing hardcoded tab data (the Fase 2 regression) and starter leftovers.
- API demo endpoints branch on `settings.demo_mode`; keep that gate when adding contract stubs that lack real auth. A new client endpoint takes `principal: CurrentPrincipal` — a `Depends`, not a header read — and ships with a negative-permission test (`test_authorization.py`).
- Adding a realm user means adding it to `SEED_USERS` in the same commit, with the same UUID — the consistency test is what keeps "authenticates but matches no row" from shipping.
- Every feature ships with an FDD (`docs/fdd/`) carrying acceptance criteria, telemetry, tests, and AI eval cases; prompt/retriever/model/tool changes require AI evals (`docs/ai/`).
