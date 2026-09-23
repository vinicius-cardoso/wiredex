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

## Consequences

- Full history and auditability for free, and "undo" becomes a compensating
  movement.
- Concurrency needs care: balance rows get optimistic locking with a
  `version` column, and a conflict is retried.
- Hand corrections still work, as an `ADJUST` movement with a reason.
