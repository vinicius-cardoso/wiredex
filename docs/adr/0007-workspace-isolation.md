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

## Consequences

- Isolation holds even if a query forgets its filter.
- RLS makes migrations and debugging slightly harder: admin tasks use a
  separate role.
