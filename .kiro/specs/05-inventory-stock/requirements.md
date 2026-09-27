# Requirements Document

## Introduction

Inventory stock, the first of three specs in `v0.4.0`: a new `inventory` module with a
location tree, stock kept in an append-only ledger of movements, a balance projection
written in the same transaction, and the parts page showing how much of each part is in
stock and where. It implements the lots, movements and balances that
[docs/architecture.md](../../../docs/architecture.md) and
[ADR 0002](../../../docs/adr/0002-stock-ledger.md) plan, for the three movement kinds this
release covers: `RECEIVE`, `ADJUST` and `MOVE`. The requirements were written against
[design.md](design.md), which came first (Design-First).

Acceptance criteria use EARS: `WHEN <condition> THE SYSTEM SHALL <behaviour>`. Every
criterion acts inside the caller's workspace.

Owner decisions (2026-09-26), final and reflected below: unit-tracked is a category
property inherited by subcategories (Requirement 6); no printed QR labels, only
human-readable short codes (Requirement 2); a change history is not part of `v0.4.0`;
`v0.4.0` records `RECEIVE`, `ADJUST` and `MOVE` only (Requirement 4).

## Glossary

- **The owner**: the single real user. A guest acts the same way inside their demo bench.
- **Location**: a place stock sits, in a tree (room → cabinet → drawer → bin), each with a
  short code.
- **Lot**: the pairing of one part with one location. Its count lives in a balance, its
  history in the ledger. There is at most one lot per (part, location).
- **Movement**: one append-only ledger row — one lot, one signed quantity, one kind
  (`RECEIVE`, `ADJUST` or `MOVE` this release), one optional reason.
- **Balance**: the projection of a lot's ledger: `on_hand`, `reserved`, `available`, with
  `available = on_hand - reserved`. In `v0.4.0` `reserved` is always zero.
- **Short code**: a human-readable label, `WX-L-NNNN` for a location, sequential per
  workspace. No QR.
- **Unit-tracked**: a part whose category is marked "tracked individually"; it is received
  as units (next spec), never as a loose lot count.

## Requirements

### Requirement 1: Location tree

**User Story:** As the owner, I want a tree of storage locations, so that "where is the
BME280" has an answer more precise than "somewhere on the bench".

#### Acceptance Criteria

1. WHEN a location is created with a name and no parent THE SYSTEM SHALL store it as a root
   location of the current workspace, assign it the next short code, and answer with its id
   and code.
2. WHEN a location is created with a parent THE SYSTEM SHALL store it as that parent's child.
3. WHEN a location is created with a name that a sibling already uses THE SYSTEM SHALL reject
   it with 409 and leave the tree unchanged, including when both are root locations.
4. WHEN a location is created more than 6 levels deep THE SYSTEM SHALL reject it with 422 and
   name the limit.
5. WHEN a location is moved under one of its own descendants, or under itself, THE SYSTEM
   SHALL reject it with 422 and leave the tree unchanged.
6. WHEN a location is moved so that any of its descendants would sit deeper than 6 levels THE
   SYSTEM SHALL reject it with 422.
7. WHEN a location is renamed to a name a sibling already uses THE SYSTEM SHALL reject it
   with 409.
8. WHEN a location is renamed or moved THE SYSTEM SHALL keep its short code unchanged.
9. WHEN a location is renamed to its current name THE SYSTEM SHALL answer 200 and commit
   nothing.
10. WHEN a location that has children or holds any lot is deleted THE SYSTEM SHALL reject it
    with 409, say which of the two blocks it, and delete nothing.
11. WHEN a location with no children and no lots is deleted THE SYSTEM SHALL delete it.
12. WHEN the location tree is requested THE SYSTEM SHALL return every location of the
    workspace with its parent, its short code, its child count and the number of lots it
    holds.

### Requirement 2: Short codes

**User Story:** As the owner, I want each location to carry a short human-readable code, so
that I can refer to a bin by `WX-L-0007` without a QR scanner.

#### Acceptance Criteria

1. WHEN a location is created THE SYSTEM SHALL assign it the next code of the form
   `WX-L-NNNN`, sequential within the workspace, starting at `WX-L-0001`.
2. WHEN two locations are created in the same workspace THE SYSTEM SHALL give them different
   codes, with no code handed out twice, even under concurrent creation.
3. WHEN locations are created in two different workspaces THE SYSTEM SHALL number each
   workspace's codes independently, so both may hold a `WX-L-0001`.
4. WHEN the workspace passes 9999 locations THE SYSTEM SHALL widen the number to five digits
   (`WX-L-10000`) rather than fail or wrap.
5. WHEN a location's code is used as a search term THE SYSTEM SHALL match it as a
   case-insensitive substring.
6. WHEN a short code is assigned THE SYSTEM SHALL never change it or reuse it for another
   location.

### Requirement 3: Stock lots and balances

**User Story:** As the owner, I want each part's quantity kept per location, so that "180
resistors" can mean "150 in drawer 3, 30 in the parts box".

#### Acceptance Criteria

1. WHEN a part is first received into a location THE SYSTEM SHALL create one lot for that
   (part, location) pair.
2. WHEN a part is received into a location that already has a lot for it THE SYSTEM SHALL
   reuse that lot rather than create a second.
3. WHEN a lot exists THE SYSTEM SHALL keep exactly one balance for it, with `on_hand`,
   `reserved` and `available`.
4. WHEN a balance is read THE SYSTEM SHALL report `available` as `on_hand` minus `reserved`.
5. WHEN any movement is recorded in `v0.4.0` THE SYSTEM SHALL leave `reserved` at zero, so
   `available` equals `on_hand`.
6. WHEN a movement would take a lot's `on_hand` below zero THE SYSTEM SHALL reject it and
   change no balance.
7. WHEN any movement is applied THE SYSTEM SHALL keep `0 <= reserved <= on_hand` for the lot.

### Requirement 4: Movements — receive, adjust, move

**User Story:** As the owner, I want stock changes recorded as movements, so that a count is
always the sum of what happened, not a number I edited in place.

#### Acceptance Criteria

1. WHEN a quantity of a part is received into a location THE SYSTEM SHALL append one
   `RECEIVE` movement of that positive quantity, raise the lot's `on_hand` by it, and answer
   with the new balance.
2. WHEN a receive names a part that does not exist in the workspace THE SYSTEM SHALL reject
   it with 404 and record nothing.
3. WHEN a part is adjusted to an absolute counted quantity THE SYSTEM SHALL set the lot's
   `on_hand` to exactly that quantity and append one `ADJUST` movement whose change is the
   counted quantity minus the previous `on_hand`.
4. WHEN an adjust carries a reason THE SYSTEM SHALL store the reason on the movement, and
   SHALL accept only `recount`, `damaged`, `lost`, `found` or `correction`.
5. WHEN a quantity of a part is moved from one location to another THE SYSTEM SHALL append
   two movements sharing one move group — a negative on the source lot and an equal positive
   on the destination lot — in one transaction.
6. WHEN a move is recorded THE SYSTEM SHALL leave the workspace's total `on_hand` for that
   part unchanged, moving only its distribution across locations.
7. WHEN a move asks for more than the source lot's `on_hand` THE SYSTEM SHALL reject it with
   409 and write neither movement.
8. WHEN a move names the same location for source and destination THE SYSTEM SHALL reject it
   with 422.
9. WHEN a move's destination has no lot for the part THE SYSTEM SHALL create it as part of
   the same transaction.
10. WHEN any movement is recorded THE SYSTEM SHALL never update or delete an existing
    movement row.
11. WHEN a `RESERVE`, `RELEASE`, `CONSUME` or `RETURN` is attempted in `v0.4.0` THE SYSTEM
    SHALL offer no way to record one, because those arrive with builds in `v0.5.0`.

### Requirement 5: The projection and rebuild

**User Story:** As the owner, I want the balances to be derivable from the ledger, so that a
projection I distrust can be rebuilt and checked.

#### Acceptance Criteria

1. WHEN a lot's movements are summed THE SYSTEM SHALL find their total equal to the lot's
   stored `on_hand`.
2. WHEN `wiredex stock rebuild` runs THE SYSTEM SHALL recompute every balance from the ledger
   and replace the projection, in one transaction per workspace.
3. WHEN a rebuild finishes THE SYSTEM SHALL produce a projection equal, balance for balance,
   to the one written incrementally.
4. WHEN a movement is applied incrementally THE SYSTEM SHALL update the projection in the
   same transaction as the movement, so a committed movement never lacks its balance effect.
5. WHEN two movements on the same lot are committed concurrently THE SYSTEM SHALL serialize
   them through the balance's version, retry the loser, and never lose a movement's effect.

### Requirement 6: Unit-tracked parts are refused as lots

**User Story:** As the owner, I want a part in a unit-tracked category to be received as
units, not as a loose count, so that a board I care about individually never becomes an
anonymous quantity.

#### Acceptance Criteria

1. WHEN a category is marked "tracked individually" THE SYSTEM SHALL treat every part in it
   and in its subcategories as unit-tracked, unless a subcategory overrides the flag.
2. WHEN a category leaves the flag unset THE SYSTEM SHALL inherit the nearest ancestor's
   value, and treat the part as lot-counted if nothing in the chain sets it.
3. WHEN a lot receive, adjust or move names a unit-tracked part THE SYSTEM SHALL reject it
   with 422 and say the part is tracked as units.
4. WHEN a category's flag is changed THE SYSTEM SHALL apply it to future receives only, and
   leave existing lots as they are.

### Requirement 7: Stock shown per part

**User Story:** As the owner, I want each part to show how much is in stock and where, so
that the catalog answers "do I have one, and which drawer".

#### Acceptance Criteria

1. WHEN the parts list is shown THE SYSTEM SHALL display each part's total `on_hand` summed
   across its lots.
2. WHEN totals for a page of parts are requested THE SYSTEM SHALL return them in one query,
   without loading a balance per row.
3. WHEN a part's stock is requested THE SYSTEM SHALL return its total `on_hand` and a
   breakdown by location, each with the location's code and name.
4. WHEN a part has never been received THE SYSTEM SHALL report a total of zero and an empty
   breakdown, not an error.

### Requirement 8: Workspace isolation

**User Story:** As the owner, I want a guest's stock and locations invisible to mine, so that
lending a demo account is not a risk.

#### Acceptance Criteria

1. WHEN any inventory request is made THE SYSTEM SHALL resolve the caller's workspace from
   their session and act only inside it.
2. WHEN a request carries no valid session THE SYSTEM SHALL answer 401 and touch no inventory
   data.
3. WHEN a location, lot or movement of another workspace is requested by id THE SYSTEM SHALL
   answer 404, not 403, so ids in other workspaces stay unguessable.
4. WHEN the application connects as its non-owner database role THE SYSTEM SHALL have
   row-level security deny reads and writes of another workspace's inventory rows, even for a
   query that forgot its filter.
5. WHEN a workspace's short-code counter is advanced THE SYSTEM SHALL keep it invisible and
   untouchable from another workspace.
6. WHEN a guest's demo workspace is reset THE SYSTEM SHALL restore its sample locations and
   stock, after its sample parts are restored.

### Requirement 9: Web

**User Story:** As the owner, I want to manage locations and stock in a browser, so that
inventory is usable from the bench, not only from curl.

#### Acceptance Criteria

1. WHEN the locations page loads THE SYSTEM SHALL show the tree with each location's code, and
   let a location be added, renamed, moved and deleted.
2. WHEN a location can't be deleted because it holds lots or has children THE SYSTEM SHALL say
   so without leaving the page.
3. WHEN a part page is opened THE SYSTEM SHALL show the part's total stock and its breakdown
   by location, and offer receive, adjust and move.
4. WHEN a part is received, adjusted or moved from the part page THE SYSTEM SHALL update the
   shown stock without a full reload.
5. WHEN an adjust is entered THE SYSTEM SHALL ask for the absolute counted quantity and a
   reason, not a delta.
6. WHEN a category is edited THE SYSTEM SHALL offer a tri-state "tracked individually"
   control — inherit, yes, no — and show the resolved answer when set to inherit.
7. WHEN any inventory screen is rendered THE SYSTEM SHALL take every string from an i18n key
   present in both `en.json` and `pt-BR.json`, and every colour from a theme token.
8. WHEN an inventory screen is operated by keyboard alone THE SYSTEM SHALL expose every
   control with a role and an accessible name, including the location tree.

### Requirement 10: Non-functional

**User Story:** As the owner, I want inventory to hold the architecture's lines and the
ledger's invariants, so that the module stays correct and cheap to run.

#### Acceptance Criteria

1. WHEN a location's ancestor chain is read THE SYSTEM SHALL read it in a single database
   round trip.
2. WHEN the parts list requests stock totals THE SYSTEM SHALL answer in one query for the
   whole page.
3. WHEN the inventory and catalog-flag migrations are applied THE SYSTEM SHALL be reversible,
   and the up → down → up round trip SHALL pass.
4. WHEN the inventory module is linted THE SYSTEM SHALL satisfy the import-linter contracts:
   the domain imports no framework, layers point inward, and inventory imports neither
   catalog nor identity.
5. WHEN routes or schemas change THE SYSTEM SHALL have `packages/api-client` regenerated, so
   CI's contract gate passes.
6. WHEN the API test suite runs THE SYSTEM SHALL keep total coverage at or above 90 %, and the
   web suite at or above 85 %.
7. WHEN the stock ledger's invariants are tested THE SYSTEM SHALL check them with Hypothesis,
   satisfying the README's `v0.4.0` property-test gate.
