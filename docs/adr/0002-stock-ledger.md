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
- **Units ride the ledger.** Receiving N units of a part is its lot's receipt: one
  `RECEIVE` of N and N unit rows, in one transaction. A unit-tracked lot's `on_hand`
  equals its number of `in_stock` units, so totals and `wiredex stock rebuild` treat
  both kinds of part alike.
- Moving a unit is the two-row `MOVE` of 1, with the unit repointed to the destination
  lot in the same transaction.
- Retiring a unit is an `ADJUST −1` (reason `damaged` or `lost`) and un-retiring it an
  `ADJUST +1` (reason `found`), so the pair leaves stock where it was. Only a retired unit
  can be deleted, and its movements stay.
- Quick-add and sheet import record ordinary `RECEIVE`s, one per row, in the transaction
  that may also define the part.

## Implementation (v0.5)

- **The four reservation kinds each name their revision.** `RESERVE` raises `reserved`,
  `RELEASE` lowers it, `CONSUME` lowers `on_hand` and `reserved` together, and `RETURN` raises
  `on_hand`. `ck_stock_movements_revision_named` holds that only these four carry a
  `revision_id`, and `ck_stock_movements_revision_sign` holds their sign, both in the database.
- **A reservation chooses what it takes:** named units first, then the lots with the most
  available stock, ties broken by location code, units before loose pieces, one `RESERVE` per
  lot.
- **Units are reserved and built one by one,** `units.revision_id` naming the revision while a
  unit is held.
- **Reserved stock is a hard hold.** A recount below it or a move past the available stock is
  refused, so a build consumes exactly what was reserved. A part whose category resolves *not
  stocked* is refused `RECEIVE` and is never reserved.
- `wiredex stock rebuild` folds all seven kinds, reserved included.
- **Append-only stays what it was:** `REVOKE UPDATE ON stock_movements FROM wiredex_app`, not
  a trigger, with DELETE kept for the demo reset.

## Consequences

- Full history and auditability for free, and "undo" becomes a compensating
  movement.
- Concurrency needs care: balance rows get optimistic locking with a
  `version` column, and a conflict is retried.
- Hand corrections still work, as an `ADJUST` movement with a reason.
