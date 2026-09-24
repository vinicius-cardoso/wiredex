# 0007. Workspace isolation with Postgres RLS and a demo workspace

- **Status:** Accepted
- **Date:** 2026-09-22

## Context

Only the owner uses Wiredex, but sometimes someone needs to try it. They must
never see the owner's real inventory.

## Decision

- Every domain row carries a `workspace_id`. Users get access through
  `Membership(user, workspace, role)`.
- Repositories always filter by the current workspace (**first gate**).
- Postgres **Row-Level Security** policies filter on
  `current_setting('app.workspace_id')`, set with `SET LOCAL` per transaction
  (**second gate**). The app connects as a non-owner role, so the policies
  can't be bypassed.
- A guest gets a **demo workspace** seeded with realistic sample data and can
  do anything in it. A timer resets it nightly. Guest accounts can have an
  expiry date.

## Implementation (v0.2)

- Two logins. `wiredex` owns the schema and runs migrations
  (`WIREDEX_ADMIN_DATABASE_URL`). `wiredex_app` (migration 0004) can read and write
  rows, owns nothing and isn't a superuser; the API logs in as it
  (`WIREDEX_DATABASE_URL`). `wiredex db upgrade` sets its password from that URL.
- A table of workspace data calls `isolate_by_workspace(op.execute, "<table>")` in the
  migration that creates it (`shared_kernel/infrastructure/row_security.py`).
- `SqlUnitOfWork(session_factory, workspace_id)` runs
  `set_config('app.workspace_id', …, true)` when its transaction starts. The setting
  ends with the transaction, so a pooled connection never carries it to the next
  request. Without a workspace, isolated tables look empty and refuse writes.
- Identity tables (users, workspaces, memberships, sessions) aren't isolated: logging
  in has to read them before any workspace is known.
- Each guest gets a demo workspace of their own (`wiredex demo invite`), so guests
  never see each other's changes either. `wiredex demo reset`, nightly from a
  systemd timer, deletes expired guests with their demo workspaces; each module
  adds restoring its sample data there.

## Consequences

- Isolation holds even if a query forgets its filter.
- RLS makes migrations and debugging slightly harder: admin tasks use a
  separate role.
