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
- The isolated tables so far: `categories`, `attribute_definitions`,
  `part_definitions` and `pins` (catalog, v0.3), `files` and `attachments` (files,
  v0.3), and, from inventory (v0.4), `locations`, `short_code_counters`,
  `stock_lots`, `stock_movements`, `stock_balances` and, from tracked units,
  `units`, `projects`, `revisions`, `bom_lines` and `bom_designators` (projects,
  v0.5), `nets` and `net_pins` (projects, v0.6), `firmware`, `firmware_revisions`,
  `firmware_versions`, `source_files` and `flashes` (firmware, v0.7), and `history_changes`
  and `history_entries` (history, v0.8). `stock_balances` keys on `lot_id` but still carries
  its own `workspace_id` so the policy has a column to filter on.
- Quick-add and sheet import add no table. Their unit of work scopes one transaction
  to the workspace and binds catalog's repositories and inventory's to it, so both
  gates cover a new part and its first stock together.
- Each guest gets a demo workspace of their own (`wiredex demo invite`), so guests
  never see each other's changes either. `wiredex demo reset`, nightly from a
  systemd timer, deletes expired guests with their demo workspaces; each module
  adds restoring its sample data there.

## Implementation (v0.8)

- The trash adds no table. It adds `trashed_at` to four tables that are already isolated
  ([ADR 0014](0014-soft-delete-and-trash.md)). A record in the trash is still its workspace's,
  under both gates.
- History's two tables are isolated like the rest ([ADR 0015](0015-history-by-triggers.md)).
  The trigger takes each change's `workspace_id` from the row it records. `wiredex_app` can
  read and delete them but can't `INSERT` or `UPDATE` them, because the trigger writes as the
  schema owner. A demo bench's history is cleared when the bench is seeded and at each nightly
  reset, so a guest's bench starts each day with no history.
- The cross-module reads `v0.8.0` adds (the trash, the history restores, the dashboard and the
  search) each name the workspace in every transaction they open, like any other use case.

## Consequences

- Isolation holds even if a query forgets its filter.
- RLS makes migrations and debugging slightly harder: admin tasks use a
  separate role.
