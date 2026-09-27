# Requirements Document

## Introduction

Tracked units, the second of three specs in `v0.4.0`: units of parts whose category is marked
"tracked individually", each with a human-readable short code, an optional serial and MAC, a
location and a status. It implements the `UNIT` that
[docs/architecture.md](../../../docs/architecture.md) and
[ADR 0002](../../../docs/adr/0002-stock-ledger.md) plan. The requirements were written against
[design.md](design.md), which came first (Design-First).

This spec builds on [inventory-stock](../inventory-stock/requirements.md): a unit is
additional identity over stock that is already counted through the ledger, not a second
counting system. Receiving units still writes the ordinary lot, `RECEIVE` movement and
balance; a unit adds a code, a serial, a MAC, a location and a status on top.

Acceptance criteria use EARS: `WHEN <condition> THE SYSTEM SHALL <behaviour>`. Every criterion
acts inside the caller's workspace.

## Glossary

- **The owner**: the single real user. A guest acts the same way inside their demo bench.
- **Unit**: one physical, individually tracked item — a dev board, say — with a short code, an
  optional serial and MAC, a location and a status. Exactly one thing.
- **Unit-tracked part**: a part whose category is "tracked individually" (the flag from the
  inventory-stock spec). Its stock is received as units, never as a loose lot count.
- **Status**: `in_stock` (counts toward the lot's `on_hand`) or `retired` (does not).
- **Serial**: an optional maker's serial number, unique per part within a workspace.
- **MAC**: an optional MAC address, normalized to `aa:bb:cc:dd:ee:ff`, unique per workspace.
- **Short code**: a unit's human-readable label, `WX-U-NNNN`, sequential per workspace. No QR.

## Requirements

### Requirement 1: Receiving units

**User Story:** As the owner, I want to receive several boards at once and have each become a
tracked item, so that I can tell my three identical ESP32s apart later.

#### Acceptance Criteria

1. WHEN N units of a unit-tracked part are received into a location THE SYSTEM SHALL create N
   units, each with its own short code, and record the stock as one `RECEIVE` movement of N on
   that (part, location) lot, in one transaction.
2. WHEN units are received into a location that has no lot for the part THE SYSTEM SHALL create
   the lot as part of the same transaction.
3. WHEN units are received for a part that does not exist in the workspace THE SYSTEM SHALL
   answer 404 and create nothing.
4. WHEN units are received THE SYSTEM SHALL leave the lot's `on_hand` equal to the number of
   its `in_stock` units.
5. WHEN a lot-counted part is received as units THE SYSTEM SHALL reject it with 422 and say the
   part is counted in lots.
6. WHEN a unit-tracked part is received as a loose lot count (the inventory-stock receive) THE
   SYSTEM SHALL reject that with 422 and say the part is tracked as units.
7. WHEN units are received with a serial or MAC given per unit THE SYSTEM SHALL store each on
   its unit, validating it before writing anything.

### Requirement 2: Short codes

**User Story:** As the owner, I want each unit to carry a code like `WX-U-0042`, so that I can
label and find a board without a QR scanner.

#### Acceptance Criteria

1. WHEN a unit is created THE SYSTEM SHALL assign it the next code of the form `WX-U-NNNN`,
   sequential within the workspace, from the same counter locations use.
2. WHEN N units are received at once THE SYSTEM SHALL give them N distinct, consecutive codes,
   with no code handed out twice, even under concurrent receipts.
3. WHEN the workspace passes 9999 units THE SYSTEM SHALL widen the number to five digits
   (`WX-U-10000`) rather than fail or wrap.
4. WHEN a unit's code is assigned THE SYSTEM SHALL never change it or reuse it for another unit.
5. WHEN a code, serial or MAC is used as a search term THE SYSTEM SHALL match it as a
   case-insensitive substring.

### Requirement 3: Status and stock agreement

**User Story:** As the owner, I want a dead board to stop counting toward my stock, so that "I
have 5 ESP32s" doesn't include the one that no longer works.

#### Acceptance Criteria

1. WHEN a unit is retired THE SYSTEM SHALL set its status to `retired` and record an `ADJUST`
   of −1 on its lot, so the lot's `on_hand` drops by one.
2. WHEN a retired unit is un-retired THE SYSTEM SHALL set its status to `in_stock` and record
   an `ADJUST` of +1 on its lot.
3. WHEN a unit is `retired` THE SYSTEM SHALL not count it toward its lot's `on_hand`.
4. WHEN a unit is `in_stock` THE SYSTEM SHALL count it toward its lot's `on_hand`.
5. WHEN a unit is retired and then un-retired THE SYSTEM SHALL return the lot's `on_hand` to
   its starting value.
6. WHEN a unit already has the target status THE SYSTEM SHALL answer without recording a
   movement.
7. WHEN `v0.4.0` runs THE SYSTEM SHALL offer only `in_stock` and `retired`, because
   `in_use`/`reserved` belong to the `v0.5.0` build lifecycle.

### Requirement 4: Moving a unit

**User Story:** As the owner, I want to move one board to another drawer, so that where a unit
is stays as precise as where a lot is.

#### Acceptance Criteria

1. WHEN a unit is moved to another location THE SYSTEM SHALL record the stock effect as the
   inventory-stock `MOVE` of quantity 1 and repoint the unit to the destination lot, in one
   transaction.
2. WHEN a unit is moved THE SYSTEM SHALL leave the workspace's total `on_hand` for the part
   unchanged, moving only the unit and the two lots' distribution.
3. WHEN a unit is moved to a location with no lot for the part THE SYSTEM SHALL create the lot
   as part of the same transaction.
4. WHEN a unit is moved to the location it already sits in THE SYSTEM SHALL reject it with 422.
5. WHEN a retired unit is moved THE SYSTEM SHALL reject it with 422.
6. WHEN a unit-tracked part is moved as a loose quantity (the inventory-stock move) THE SYSTEM
   SHALL reject it with 422, because its units would stay behind in the source lot.
7. WHEN the same unit is retired or moved by two requests at once THE SYSTEM SHALL apply it
   once, so its lots' `on_hand` still equals their `in_stock` units.

### Requirement 5: Identity — serial and MAC

**User Story:** As the owner, I want a unit's serial and MAC recorded, so that I can match a
board on the bench to its row in Wiredex.

#### Acceptance Criteria

1. WHEN a unit is given a serial THE SYSTEM SHALL reject it with 409 if another unit of the
   same part in the workspace already has that serial, ignoring case.
2. WHEN a unit is given a MAC THE SYSTEM SHALL reject it with 409 if another unit in the
   workspace already has that MAC.
3. WHEN a MAC is entered in any common spelling (`AA-BB-…`, `aabb.ccdd.…`, `aabbccddeeff`,
   colon-separated) THE SYSTEM SHALL store it as canonical `aa:bb:cc:dd:ee:ff`.
4. WHEN a MAC is not six hex octets THE SYSTEM SHALL reject it with 422.
5. WHEN a unit's serial or MAC is left blank THE SYSTEM SHALL allow it, for any number of units.
6. WHEN a unit's serial or MAC is changed THE SYSTEM SHALL store the change, refusing a
   duplicate, and commit nothing if unchanged.

### Requirement 6: Finding and removing units

**User Story:** As the owner, I want to find a unit by its code, serial or MAC and tidy up dead
ones, so that the unit list stays useful.

#### Acceptance Criteria

1. WHEN a part's units are requested THE SYSTEM SHALL list them with code, serial, MAC, status
   and location.
2. WHEN a location's units are requested THE SYSTEM SHALL list the units sitting in it.
3. WHEN a unit search is made THE SYSTEM SHALL match the term against code, serial and MAC as a
   case-insensitive substring, and return each unit with its part, location and status.
4. WHEN a unit is deleted THE SYSTEM SHALL allow it only if the unit is `retired`, and reject an
   `in_stock` unit with 409.
5. WHEN a retired unit is deleted THE SYSTEM SHALL remove the unit and leave its ledger history
   intact.

### Requirement 7: Workspace isolation

**User Story:** As the owner, I want a guest's units invisible to mine, so that lending a demo
account stays safe.

#### Acceptance Criteria

1. WHEN the application connects as its non-owner database role THE SYSTEM SHALL have row-level
   security deny reads and writes of another workspace's units.
2. WHEN a unit of another workspace is requested by id THE SYSTEM SHALL answer 404, not 403.
3. WHEN a unit search is made THE SYSTEM SHALL never match a unit in another workspace.
4. WHEN a guest's demo workspace is reset THE SYSTEM SHALL restore its sample units, after its
   sample stock is restored.

### Requirement 8: Web

**User Story:** As the owner, I want to receive, find and manage units in a browser, so that
tracking boards is usable from the bench.

#### Acceptance Criteria

1. WHEN a unit-tracked part's page is opened THE SYSTEM SHALL offer *Receive units* rather than
   the loose *Receive*, and list the part's units beneath the per-location breakdown.
2. WHEN units are received in the browser THE SYSTEM SHALL take a quantity, a destination
   location, and an optional serial and MAC per unit, and show the minted codes on success.
3. WHEN a unit is shown THE SYSTEM SHALL display its code, serial, MAC, status and location, and
   offer relabel, move, retire, un-retire and (when retired) delete.
4. WHEN a unit is searched THE SYSTEM SHALL let the term match a code, serial or MAC, and open
   the found unit.
5. WHEN a MAC is entered THE SYSTEM SHALL show its canonical form after it validates, without
   rewriting the input before then.
6. WHEN any unit screen is rendered THE SYSTEM SHALL take every string from an i18n key present
   in both `en.json` and `pt-BR.json`, and every colour from a theme token.
7. WHEN a unit screen is operated by keyboard alone THE SYSTEM SHALL expose every control with a
   role and an accessible name.

### Requirement 9: Non-functional

**User Story:** As the owner, I want units to hold the module's lines and the ledger's
invariants, so that the feature stays correct and cheap to run.

#### Acceptance Criteria

1. WHEN a lot's `on_hand` and its `in_stock` units are compared THE SYSTEM SHALL find them
   equal for a unit-tracked part, at every step of any operation sequence.
2. WHEN `wiredex stock rebuild` runs THE SYSTEM SHALL reproduce every lot's balance, units
   included, since units count through the same ledger.
3. WHEN migration `0012` is applied THE SYSTEM SHALL be reversible, and the up → down → up
   round trip SHALL pass.
4. WHEN the inventory module is linted THE SYSTEM SHALL still satisfy the import-linter
   contracts, importing neither catalog nor identity.
5. WHEN routes or schemas change THE SYSTEM SHALL have `packages/api-client` regenerated, so
   CI's contract gate passes.
6. WHEN the API test suite runs THE SYSTEM SHALL keep total coverage at or above 90 %, and the
   web suite at or above 85 %.
7. WHEN the unit-and-ledger agreement is tested THE SYSTEM SHALL check it with Hypothesis,
   under the README's `v0.4.0` property-test gate.
