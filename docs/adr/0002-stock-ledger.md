# 0002. Model stock as an append-only ledger with reservations

- **Status:** Accepted
- **Date:** 2026-09-22

## Context

Parts are shared across projects. Editing a quantity by hand ("I have 12")
can't answer "where did the other 3 go?", and it can't stop two projects
from promising the same ESP32.

## Decision

- Every change in stock is a **`StockMovement`** row that is never updated or
  deleted: `RECEIVE`, `ADJUST`, `MOVE`, `RESERVE`, `RELEASE`, `CONSUME`,
  `RETURN`, each with a quantity, a lot, a reason and an optional reference to
  a project revision.
- A **`StockBalance`** projection (`on_hand`, `reserved`, `available`) is
  written in the same transaction as the movement, so reads stay fast. A CLI
  command can rebuild it from the ledger.
- Invariant enforced in the domain: `available >= 0` and `reserved <= on_hand`.
- Bulk parts are counted per **lot** (part + location). Parts that matter
  individually, like dev boards, are also tracked as **units** with a label and
  an optional serial or MAC.

## Implementation (v0.4)

- `RECEIVE`, `ADJUST` and `MOVE` shipped; the rest of the vocabulary waits for
  projects to need it.
- A `MOVE` is **two rows** sharing a `move_group` id: a negative movement out of
  the source lot and a positive one into the destination, written and balanced in
  one transaction. Reading the group back gives the whole move.
- An `ADJUST` takes the **absolute counted quantity** ("I have 12") but stores the
  signed **delta** against the current balance, so the ledger still sums to the
  on-hand total and a rebuild reproduces it.
- `reserved` stays **zero**: nothing reserves stock until projects arrive in
  `v0.5.0`. The column and the `reserved <= on_hand` invariant exist now so the
  projection's shape doesn't change later.
- `wiredex stock rebuild` folds the ledger per workspace with
  `Balances.rebuilt_from` and replaces the projection, the CLI escape hatch the
  decision promised.

## Consequences

- Full history and auditability for free, and "undo" becomes a compensating
  movement.
- Concurrency needs care: balance rows get optimistic locking with a
  `version` column, and a conflict is retried.
- Hand corrections still work, as an `ADJUST` movement with a reason.
