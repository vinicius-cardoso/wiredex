# 0015. Record history in Postgres with triggers

- **Status:** Proposed
- **Date:** 2026-10-01

## Context

`v0.8.0` adds history for everything: each change with who made it, when, and the values before
and after; a timeline on each record's page; a workspace activity feed; and restoring a past
version as a new change.

Recording from the use cases would require every write path in five modules to remember it, and a
path that forgot would leave a silent gap. The architecture proposed domain events for an audit
log (§5). Wiredex dispatches no events, though, and an event raised in a transaction that rolls
back would have to be dropped as well. The recording also has to keep working under the previous
API, because a failed deploy rolls back the API but never the schema
([deploy/README.md](../../deploy/README.md)).

This record was written without the owner, by 17-history, and stays Proposed until the owner
reviews it.

## Decision

- **Postgres does the recording.** Migration `0023` adds one trigger function,
  `record_history()`, which runs after every insert, update and delete on 18 tracked tables. The
  `track_history(op.execute, table)` migration helper, next to `isolate_by_workspace`, attaches
  it. A write that rolls back records nothing, and no write path can skip recording.
- **What is tracked:**
  - parts with their pins, and units with their flashes;
  - projects with their revisions, BOM lines, designators, nets and net pins;
  - firmware with its versions, source files and runs-on links;
  - attachments, categories with their attribute definitions, and locations.

  The stock ledger is not tracked, since it already is the history of stock
  ([ADR 0002](0002-stock-ledger.md)). Neither are files, which are reached through their
  attachments, or the identity tables, which hold secrets and aren't workspace data.
- **A change is one transaction's writes to one record and what it holds.** `history_changes`
  has one row per transaction and record. `history_entries` has one row per row written, with
  whole-row `before` and `after` snapshots and the names of the fields that changed. An update
  that changes only `updated_at`, or nothing at all, is skipped.
- **Who and why travel with the transaction, as the workspace already does.** `SqlUnitOfWork`
  sets `app.user_id`, `app.user_name` and `app.change_reason` together with `app.workspace_id`.
  The values come from a context that the composition root fills once it has authenticated the
  request. The command line and the nightly jobs set no user, so their changes read as Wiredex's.
  The user's name is stored as it was at the time of the change.
- **The API's role can read and delete history, never write or change it.** `record_history()`
  is `SECURITY DEFINER` with a fixed `search_path`, so it writes as the schema owner, and
  `wiredex_app` loses `INSERT` and `UPDATE` on both tables. A demo bench's reset still needs to
  delete.
- **A `history` module reads the changes**: the feed and each record's timeline, newest first, 50
  per page by default and at most 100, with a cursor on the change id. A change lists at most 20
  row changes. Values longer than 300 characters are shortened when read.
- **A restore goes through the module that owns the record.** It puts back the `before` snapshot
  of the record's own row with the module's own edit (`UpdatePart`, `RelabelUnit`,
  `UpdateProject` or `UpdateFirmware`), under the reason `restore`. The module refuses anything
  its form would refuse, and the trigger records the restore as a new change. A move to the trash
  is undone through the trash ([ADR 0014](0014-soft-delete-and-trash.md)). Rows that were deleted
  stay in history as they last were and are never re-created from it.
- **No backfill.** A record's history starts with its first change after the upgrade.
- **Retention.** The owner's history is kept for good. A demo bench's history is cleared when the
  bench is seeded and at each nightly reset.

## Consequences

- Every write to a tracked table is recorded, including the previous API's after a rollback. The
  database refuses a forged or edited change, even one caused by a bug.
- Each write to a tracked table costs a trigger call and up to two inserts in the same
  transaction, and a demo reset has more rows to delete.
- Pinouts, designators and net pins are saved by replacing their rows. A one-pin edit therefore
  reads as every pin removed and added again, capped at 20 row changes per change.
- References to other records show as ids, not names.
- A table tracked later needs a branch in `history_root()` and a `track_history` call in its
  migration. A column added to a tracked table shows up in history with no extra work.
- The owner's history grows without bound. Pruning by age is left for later.
