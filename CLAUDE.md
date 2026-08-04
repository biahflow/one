# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Portal Labs — a multi-tenant client portal where customers track AI project progress, results, and decisions, with a context-aware assistant that answers **only** with evidence from the project (citations, never invention). Product docs are PT-BR; code, API, and DB identifiers are English.

The repo is a monorepo, and Fase 1 (identity, roles, RLS) is complete on both halves. **The API** validates the OIDC access token, authorizes from the `membership` and enforces Row-Level Security (ADR 0010) — every client endpoint requires `Authorization: Bearer` and answers 404, never 403, on a denial. **The web layer** is a real OIDC client: Auth.js v5 does the code exchange server-side, `proxy.ts` closes everything but `/login`, and `app/page.tsx` renders from the API. There is no fallback to fabricated data any more — 401 goes to `/login`, 404 says "no project assigned", a network failure is an error panel. Fase 1 is now closed end to end: an internal admin invites someone at `/admin`, the person gets an e-mail from Keycloak, sets a password and lands on their project. **Fase 2 is closed too**: a change in Biahflow becomes a notification in the bell and a digest e-mail, produced by the sync itself (ADR 0012). **Fase 3 closed the results pipeline** (ADR 0013): agents publish idempotent events through the one key-authenticated route, financial assumptions carry an effective range, and ROI is computed at read time from the assumption in force *on the day of the event* — so the last three demo cards and the fabricated ROI fallback are gone from the client's screen. **Fase 4 gave the assistant eyes** (ADR 0014): an internal member uploads a file at `/admin/conhecimento`, the worker turns it into page-anchored chunks with embeddings in pgvector, and the chat now cites "Documento: Contrato — página 3" instead of declaring a gap. What is still open in Fase 4: the Google Drive connector and conversation persistence — see `ROADMAP.md`.

## Architecture

Three deployables (`docs/architecture.md`):

```
Browser → Next.js BFF → FastAPI → PostgreSQL + pgvector
                         ├→ Redis/Celery → Drive, email, indexing
                         └→ MinIO/S3 → documents & transcripts
```

- **`app/` (+ `auth.ts`, `proxy.ts` at the root)** — the web frontend: stock **Next.js 16** (App Router, React 19 RSC) served by `next start` on Node, containerized like every other service (ADR 0009). `auth.ts` configures Auth.js v5 with the confidential Keycloak client; `proxy.ts` (Next 16's name for the middleware) is the session gate — a redirect for pages, a 401 for `/api/`. `app/page.tsx` is the server component: it fetches `GET /api/v1/me` and the dashboard in parallel with the token from `app/lib/session.ts`, and projects both into the props of `app/DashboardClient.tsx`, the `"use client"` UI (`answerFor()` is only the offline chat fallback). The frontend's role is BFF: it never decides authorization.
- **`apps/api/`** — FastAPI (`portal_api`), Python 3.13, Pydantic settings. `main.py` holds the REST contracts under `/api/v1`. Every client endpoint depends on `CurrentPrincipal` (`auth.py`), which validates the OIDC access token against the realm's JWKS; `identity.py` turns that principal into a `user` row (link by e-mail on first login, provision if unknown) and `access.py` decides what the user reaches — always `None` → 404, never 403.
- **`apps/api/src/portal_api/{db,models,repositories}/`** — the Postgres data layer (SQLAlchemy 2.0 + Alembic). Models live in the `portal` schema, but the metadata is **not** schema-qualified: the engine pins the connection `search_path` to `portal,public` (`db/session.py`) so DDL and reflection stay unqualified and `alembic check` sees no false drift — keep new models unqualified too. `public` is there only for pgvector's `vector` type, which the bootstrap creates in that schema; `portal` stays first, so an unqualified table still lands in it. `db/base.py` provides `TenantMixin` (adds `organization_id`; project tables also add `project_id`). Data access goes through `repositories/`: `TenantScopedRepository` filters every read and stamps every write from a `TenantContext`, enforcing org/project isolation at the app layer — the barrier *before* RLS, which is the second one below it.

## Tenancy and the database roles (ADR 0010)

Three credentials, one per kind of work, and `DATABASE_URL` is the request path:

| Setting | Role | RLS |
|---|---|---|
| `DATABASE_URL` | `portal_app` — API and worker request path | **subject to it** |
| `DATABASE_SYSTEM_URL` | `portal_system` — Biahflow webhook, sync, seed | `BYPASSRLS` |
| `DATABASE_MIGRATION_URL` | `portal_migrator` — owns the schema, runs Alembic | exempt as owner |
| `DATABASE_ADMIN_URL` | `portal_admin` — `/api/v1/admin/*`, the only writer of `membership` | **subject to it** |

`get_session(principal)` publishes the tenant context as transaction-local GUCs, in two stages: identity (`portal.subject`, `portal.email`, `portal.user_id`) and tenant (`portal.organization_id`, `portal.project_id`). The policies read those, and `current_setting(..., true)` returns NULL when unset — so **missing context yields zero rows, never an unscoped read**. `access.scoped_project`/`default_project` call `bind_tenant` themselves; if you add a resolver that returns a project, it must do the same or every later read comes back empty (`docs/runbooks/auth-failure.md`).

**Writing `membership` goes through `portal_admin` and nothing else (ADR 0011).** Its policies key on a third-stage GUC, `portal.admin_organization_id`, which `bind_admin_org` publishes *after* the caller's `internal_admin` was verified — before that the transaction sees only the caller's own memberships, which is what keeps the check from being circular. A fourth GUC, `portal.invitee_subject`, opens exactly one `user` row: the person being invited. Every admin policy is `TO portal_admin`, so the request credential is not merely missing the grant — the policy does not apply to it.

**Every new table carrying `organization_id` ships with a policy in the same migration.** A meta-test in `test_rls_isolation.py` fails CI otherwise. The app role holds `SELECT` almost everywhere, `INSERT` only on `pending_item`, `audit_log` and `agent_event` (the last one added in Fase 3 with a `WITH CHECK` on the tenant — the ingestion route is the only one that takes a project id from outside, so it is exactly where RLS has to stay as the second barrier; `agent_api_key` grants it nothing at all), `INSERT` plus a **column-scoped** `UPDATE (external_subject, notify_by_email, updated_at)` on `user`, and on `notification` a column-scoped `UPDATE (read_at, updated_at)` and nothing else — mirroring "the portal never originates status" (ADR 0006/0008) in the database itself. The column grants are the point: a policy decides which *rows*, never which *columns*, so "mark as read" and "change my e-mail preference" cannot become "rewrite the notice" or "promote myself to internal staff" (ADR 0012). Fase 4 added no write at all to the app role: `document_chunk` is SELECT-only for it, and `document` gained `INSERT/UPDATE/DELETE` for `portal_admin` alone (ADR 0014).

`notification` is the one table whose row belongs to a *person*: its policies add `user_id = portal.current_user_id()` to the tenant predicate, and nobody but `portal_system` inserts there — the sync is the producer, because the portal cannot know that something *changed* except by diffing the read model around a snapshot.
- **`apps/api/src/portal_api/worker.py`** — Celery worker for async jobs (Drive/document ingestion, the notification digest), gated on Redis. `send_project_digests` works off `emailed_at IS NULL` rather than an id list from the caller, so a re-delivered task is a no-op and a lost one is only a delay. Enqueueing is wrapped in `queue_project_digests`/`queue_pending_notification`, which swallow a dead broker: the notifications are already committed and show up in the portal either way.
- **`apps/api/src/portal_api/notifications.py`** — the only place a `Notification` is created (ADR 0012). `snapshot_state` photographs the read model *before* `sync_snapshot` writes, `diff` compares, `fan_out` inserts one row per recipient with `ON CONFLICT DO NOTHING`. Adding a new kind of notice means adding a `NotificationKind`, a branch in `diff` with a stable `dedupe_key`, and an entry in `AUDIENCE` — nothing else.
- **`apps/api/src/portal_api/agent_auth.py`** — the only alternative to OIDC on a client route (ADR 0013). Resolves `X-Agent-Key` under `portal_system` (the lookup happens *before* there is a tenant to bind — the tenant comes out of the key), then the ingestion runs in a second transaction under `portal_app` with `bind_tenant`. Every credential refusal is the same opaque 401 with the reason in the log; only the rate-limit window answers 429, because the producer has to tell pace from credentials. In its own module for the same reason `admin.py` is: "what authenticates an agent" should fit in one file.
- **`apps/api/src/portal_api/{storage,ingestion/,ai/embeddings}.py`** — the path a file takes to become citable evidence (ADR 0014). `storage.py` speaks S3 (MinIO locally), and the object key carries the whole tenant. `ingestion/extract.py` turns bytes into pages and `ingestion/chunk.py` turns pages into chunks — both pure, no DB and no network, and both obeying the one rule the citation rests on: **a chunk never spans a page boundary**, because "página 3" is either true or it is noise wearing the clothes of a source. `ai/embeddings.py` mirrors `ai/responder.py`: Voyage when `VOYAGE_API_KEY` is set, a deterministic hashing projection otherwise, same dimension either way. The distance cutoff belongs to the embedder, not to the retriever — the two vector spaces are different, and one number would serve both badly. Writing the index is the worker's job under `portal_system`; `portal_app` is SELECT-only on `document_chunk`, because a request path that can write a chunk can write the "evidence" it wants cited.
- **`apps/api/src/portal_api/results.py`** — the read-time computation. Nothing is derived on write: the event stores the integers the agent reported, and money is produced by applying the assumption in force **on the day of the event**, so raising the hourly rate today cannot reprice March. Missing basis yields `None` plus a reason in `gaps` — zero investment declares the gap instead of dividing by zero. Adding an indicator means adding it here and to `to_payload`, never to the ingestion.
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
- Access administration lives in `portal_api/admin.py` (an `APIRouter`), never in `main.py`: it is the only surface that runs under `portal_admin`, and keeping it apart is what makes "who can write membership" answerable by reading one file.
- Agent keys, financial assumptions and document upload live in `admin.py` too, for the same reason: they are the write path under `portal_admin`. A plaintext key is returned exactly once, at creation; nothing anywhere can recover it afterwards. The upload is the only route that speaks multipart, and the only one where the row is written *before* the side effect (the object key needs the row's id) — so a dead storage rolls the transaction back instead of leaving a `document` pointing at a file that does not exist.
- API demo endpoints branch on `settings.demo_mode`; keep that gate when adding contract stubs that lack real auth. A new client endpoint takes `principal: CurrentPrincipal` — a `Depends`, not a header read — and ships with a negative-permission test (`test_authorization.py`). `POST /api/v1/agent-events` is the one exception and should stay the exception: it takes a key, not a principal.
- Adding a realm user means adding it to `SEED_USERS` in the same commit, with the same UUID — the consistency test is what keeps "authenticates but matches no row" from shipping.
- Every feature ships with an FDD (`docs/fdd/`) carrying acceptance criteria, telemetry, tests, and AI eval cases; prompt/retriever/model/tool changes require AI evals (`docs/ai/`).
