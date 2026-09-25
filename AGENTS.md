# Working on Wiredex

Instructions for coding agents (Claude Code, Kiro, and others) and for people. Wiredex
is a private, single-owner system for hardware parts and projects, live at
https://wiredex.vinilabs.cc. The [README](README.md) has the product and the roadmap,
[docs/architecture.md](docs/architecture.md) the design, [docs/adr/](docs/adr/) the
decisions, and [deploy/README.md](deploy/README.md) the production runbook. Those
documents win over this file when they disagree; fix whichever is wrong.

## Repository map

| Path | What |
| --- | --- |
| `apps/api` | FastAPI + SQLAlchemy 2 (async) + Alembic, Python 3.14, managed with uv |
| `apps/web` | React 19 + TypeScript + Vite + Tailwind v4, TanStack Router and Query |
| `packages/api-client` | Typed client **generated** from the API's OpenAPI schema (ADR 0010) |
| `packages/i18n` | EN and PT-BR messages, shared by web and (later) mobile |
| `e2e` | Playwright journeys against the real API, database and production web build |
| `deploy` | Compose file, Caddy site, deploy, backup and server setup scripts |

## Commands

`make help` lists everything. The ones used most:

- `make install`, then `make hooks` once (pre-commit and commit-msg hooks).
- `make db` starts Postgres on `127.0.0.1:5442`; `make migrate` applies migrations.
- `make api` (port 8000) and `make web` (port 5173, proxies `/api`).
- `make check`: lint, types, import boundaries and unit tests; what CI runs, minus
  Docker.
- `make coverage`: every API test, integration included, with the 90 % floor
  (needs Docker).
- `make e2e`: Playwright (needs `make db`).
- `make client` after **any** change to the API's routes or schemas; CI fails when
  `packages/api-client` is stale.
- `make migration m="what it does"`, then read and fix the generated file.

pnpm isn't installed globally: use `npx -y pnpm@12.5.1 …` (the Makefile does). pnpm 12
refuses packages published less than a day ago; wait, don't add an exception.

## Architecture rules

- **Modular monolith, hexagonal modules** (ADR 0001): each module (`identity`,
  `system`, …) has `domain` → `application` → `infrastructure` / `api`, and
  dependencies point inward. `lint-imports` enforces it: domain code imports no
  framework, and only `bootstrap/` (the composition root) wires modules together.
- Routers are factories, `create_router(use_cases)`, built in `bootstrap/app.py`.
- Domain values are small immutable classes that validate themselves (`Email`,
  `Password`, `GuestLifetime`). Persistence uses imperative SQLAlchemy mapping, so
  domain classes stay plain.
- One use case, one unit of work: nothing is saved without `commit()`.
- **Workspace isolation** (ADR 0007): a table of workspace data has a
  `workspace_id` column and calls `isolate_by_workspace(op.execute, "<table>")` in
  its migration; use cases open `SqlUnitOfWork(…, workspace_id)`. The API connects as
  `wiredex_app`, which row-level security applies to; migrations run as the owner.
- **Migrations** must work with the previous release too (expand now, contract in a
  later release), never import application code, and have a working `downgrade`.
- Background jobs are `wiredex` CLI commands run by systemd timers (ADR 0011), not
  a broker.
- Web: pages live under `apps/web/src/features/<feature>/`; server state goes through
  TanStack Query; colours come from theme tokens (`bg-surface`, `text-muted`…),
  never raw hex; every user-facing string is an i18n key present in **both** locale
  files.

## Tests

- API: `pytest` runs unit tests; integration tests are marked `integration`, use
  testcontainers and are included with `-m "integration or not integration"`. mypy
  is strict for tests too, and SQLAlchemy warnings are errors.
- Web: Vitest with MSW (`src/test/server.ts` has the API fakes); query elements by
  role and accessible name, as users find them.
- E2E: `auth.setup.ts` creates the e2e account with the CLI and saves a logged-in
  session that every journey reuses. A test that logs out or revokes a session must
  log in on its own first (`logIn(page)` with `LOGGED_OUT` storage).
- New behaviour comes with tests; coverage floors are 90 % (API) and 85 % (web).

## Commits and pull requests

- [Conventional Commits](https://www.conventionalcommits.org/), checked in CI: types
  `build chore ci docs feat fix perf refactor revert style test`, optional
  `(scope)`, imperative summary. release-please builds the changelog from them.
- **Small, focused commits.** Each one must pass lint, types, import boundaries and
  the tests **on its own**, because `main` is rebase-merged and every commit lands.
  Push only after the checks pass.
- **No AI attribution:** no `Co-Authored-By` or similar trailers naming an agent.
- One PR per roadmap version, with auto-merge (`gh pr merge N --rebase --auto`).
- Versions (ADR 0012): below 1.0 a `feat` bumps the patch. A roadmap phase gets its
  minor version from a `Release-As: 0.X.0` footer on a commit that **changes
  something**: rebase merges drop empty commits.

## Safety

- **Merging a release PR deploys to production.** Only the owner decides when.
- Never change the server, OCI resources, GitHub settings or production data without
  the owner's explicit OK. Reading logs and status is fine.
- Never print, copy or commit secrets: `/srv/wiredex/.env`, `api.env`, the restic
  password, deploy keys.
- Never point tools (database clients, API collections, load tests) at production.
  Use the local stack.

## Writing

Docs, comments and commit messages are plain, concrete English. Comments say why,
not what. User-facing text exists in English and Brazilian Portuguese.
