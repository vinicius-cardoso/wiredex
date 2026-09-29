# Requirements Document

## Introduction

The build lifecycle, the last of three specs in `v0.5.0` Projects & BOM. It delivers the
phase's roadmap line *Build lifecycle: reserve, cancel, build, dismantle, each with its ledger
effect*, and the README's promise that *moving a revision to Reserved reserves stock, Built
consumes it, and Dismantled returns it*. It builds the state machine
[ADR 0003](../../../docs/adr/0003-project-revisions.md) decided, `Draft → Reserved → Built →
Dismantled` and `Reserved → Draft` on cancel, as the State pattern
[docs/architecture.md](../../../docs/architecture.md) §5 names for the revision lifecycle, and
gives [ADR 0002](../../../docs/adr/0002-stock-ledger.md)'s ledger the four kinds it has carried
unused since `v0.4.0`: `RESERVE`, `RELEASE`, `CONSUME` and `RETURN`, each naming the revision
that caused it.

It stands on the two specs before it. [08-projects-and-revisions](../08-projects-and-revisions/design.md)
stored every revision's status from its first migration, always `draft`, and left every
transition here; [09-bill-of-materials](../09-bill-of-materials/design.md) gave each revision
its BOM, the shortage report and the consumables this spec never reserves, and made a
revision's status lock its BOM. Boards tracked as units
([06-tracked-units](../06-tracked-units/design.md)) are set aside and built in one by one, so a
unit learns which revision it went into, the link 15-flash-log (`v0.7.0`) will read. The spec
also restores a reserved sample build in the demo bench, ends with the journey
docs/architecture.md §8 describes, and closes the phase with the documentation commit that
carries `Release-As: 0.5.0`. Requirements-first: [design.md](design.md) answers these.

Acceptance criteria use EARS: `WHEN <condition> THE SYSTEM SHALL <behaviour>`. Every criterion
acts inside the caller's workspace.

Owner decisions (2026-09-27) that bind every spec and reach this one: a BOM line names exactly
one part definition, with no substitutes before 1.0, so a reservation takes one part per line;
consumables, the parts whose category resolves not stocked (09), sit on BOMs but are never
reserved, consumed or returned, and never count as a shortage; one PR per spec with
auto-merge, and the release PR waits for the phase's last spec, this one, and only the owner
merges it, which deploys to production. This spec's phase-closing documentation task carries
the `Release-As: 0.5.0` footer.

Owner decisions (2026-09-28) on this spec: a dismantled revision can be deleted, like a draft,
since it holds no stock and its movements stay in the ledger; a unit built into a revision has
the status `in_use`, the name 06 planned; reserved stock is a hard hold, so a recount below the
reserved count is refused until the reservation is cancelled; and a manual rollback past
`0.5.0` first cancels or dismantles every revision holding units, which the release notes say,
since deploys only go forward.

## Glossary

- **The owner**: the single real user. A guest acts the same way inside their demo bench.
- **Status**: where a revision stands in its build lifecycle: *draft*, *reserved*, *built* or
  *dismantled* (ADR 0003, stored since 08).
- **Transition**: one of the four moves between statuses: *reserve*, *cancel*, *build* and
  *dismantle*.
- **Lot**: one part in one location (05-inventory-stock); its **balance** says how many are
  *on hand*, how many of those are *reserved*, and how many are *available*: on hand less
  reserved.
- **Free stock**: a part's available stock, summed over its lots.
- **Location code**: a location's short code, `WX-L-0003` (05), unique in the workspace.
- **Consumable**: a part whose category resolves not stocked (09-bill-of-materials).
- **Need**: the sum of the quantities of a revision's BOM lines that name one part (09).
- **Stocked need**: the need of a part that isn't a consumable.
- **Reservation**: what a reserved revision has set aside: for each lot it takes from, a
  quantity of that lot's stock.
- **Consumption**: what a built revision's build took out of stock, per part.
- **Holdings**: what a revision holds of the stock: its reservations while reserved, its
  consumption while built, and nothing otherwise.
- **Unit**: one tracked board with its short code (06-tracked-units); its **unit status** is one
  of *in stock*, *reserved*, *in use* and *retired*.
- **Named unit**: a unit the owner picks for a reservation instead of letting the system
  choose.
- **Shortage report**: 09's report of a revision's BOM against free stock: each part's need,
  available stock, how many are short, and its status.
- **Unknown part**: a part a BOM line names that the workspace's catalog no longer holds (09).

## Requirements

### Requirement 1: The build lifecycle

**User Story:** As the owner, I want every revision to move through draft, reserved, built and
dismantled, so that what a build holds of my stock always follows where the build stands.

#### Acceptance Criteria

1. WHEN a transition is asked of a revision THE SYSTEM SHALL allow exactly four: reserve from
   draft to reserved, cancel from reserved to draft, build from reserved to built, and
   dismantle from built to dismantled.
2. WHEN a transition is asked of a revision whose status doesn't allow it THE SYSTEM SHALL
   refuse it with 409, naming the status and the transition, and write nothing.
3. WHEN a transition succeeds THE SYSTEM SHALL change the revision's status, write the
   transition's stock effect and move the revision's last change, in one transaction.
4. WHEN any step of a transition fails THE SYSTEM SHALL write nothing: the status, the
   movements, the balances and the units stay as they were.
5. WHEN transitions and BOM writes to one project arrive together, or the same transition
   twice, THE SYSTEM SHALL apply them one at a time, each seeing the status and the BOM the one
   before it left, so a repeated transition is refused as not allowed.
6. WHEN a revision is dismantled THE SYSTEM SHALL keep it dismantled, a new build of it
   starting from a fork.
7. WHEN a transition names a revision that isn't in the workspace THE SYSTEM SHALL answer 404.

### Requirement 2: Reserving

**User Story:** As the owner, I want reserving a revision to set its parts aside or tell me what
is missing, so that two builds never count on the same ESP32.

#### Acceptance Criteria

1. WHEN a draft revision is reserved THE SYSTEM SHALL lock the stock its BOM needs, compute its
   shortage report from that stock, and reserve only when no part is short and none is
   unknown.
2. WHEN a reserve is refused for shortages THE SYSTEM SHALL answer 409 with the shortage
   report, naming each short part with its need, available stock and shortage, and each unknown
   part, and write nothing.
3. WHEN a revision whose BOM has no lines is reserved THE SYSTEM SHALL refuse it with 409 and
   write nothing.
4. WHEN a revision is reserved THE SYSTEM SHALL write, for every part its BOM needs that isn't
   a consumable, `RESERVE` movements naming the revision whose quantities sum to the part's
   need.
5. WHEN a reservation chooses the lots a part's need is taken from THE SYSTEM SHALL take, for
   what the named units don't cover, from the lots with the most available stock first, then
   by location code, never more than a lot's available stock, so it draws on as few lots as the
   need allows.
6. WHEN a `RESERVE` is written THE SYSTEM SHALL raise its lot's reserved by its quantity and
   leave the lot's on hand as it was.
7. WHEN a BOM line names a consumable THE SYSTEM SHALL reserve, consume and return none of it,
   and count it short never.
8. WHEN two reservations need the same stock at the same time THE SYSTEM SHALL reserve the
   second against what the first left, refusing it with its shortages when that doesn't cover
   it, so no lot's reserved passes its on hand.

### Requirement 3: Boards in builds

**User Story:** As the owner, I want to know which physical board went into which build, so
that the flash log can later say what runs on the greenhouse ESP32.

#### Acceptance Criteria

1. WHEN a reservation takes from a lot that holds units in stock THE SYSTEM SHALL reserve that
   lot's units first, one for each piece it takes, up to their number, marking each unit
   reserved and linking it to the revision.
2. WHEN a reserve names units THE SYSTEM SHALL reserve those for their parts, and choose the
   rest of each part's need automatically.
3. WHEN units are chosen automatically THE SYSTEM SHALL take, from each lot the reservation
   draws on, its units in stock in the order of their codes.
4. WHEN a reserve names a unit the workspace doesn't hold, a unit of a part the BOM doesn't
   need, the same unit twice, or more units of a part than its need THE SYSTEM SHALL refuse it
   with 422 naming the unit, and write nothing.
5. WHEN a reserve names a unit that isn't in stock THE SYSTEM SHALL refuse it with 409 naming
   the unit, and write nothing.
6. WHEN a reserved revision is built THE SYSTEM SHALL mark its reserved units in use, keeping
   their link to the revision.
7. WHEN a reservation is cancelled, or a build dismantled, THE SYSTEM SHALL put its units back
   in stock and clear their link, a dismantled build's units in the location chosen for the
   return.
8. WHEN a reserved or in-use unit is moved, retired or deleted THE SYSTEM SHALL refuse it with
   409, saying whether cancelling the reservation or dismantling the build frees it, and still
   relabel it as any unit.
9. WHEN units are received, reserved, released, built, returned, retired, un-retired or moved
   THE SYSTEM SHALL keep, for every lot whose stock came in as units, its on hand equal to its
   units in stock and reserved, and its reserved equal to its reserved units.
10. WHEN a unit is answered THE SYSTEM SHALL include its status, one of in stock, reserved,
    built and retired, and the revision it is reserved for or built into.
11. WHEN a revision's units are asked for THE SYSTEM SHALL answer the units reserved for it or
    built into it, in one query.

### Requirement 4: Cancelling a reservation

**User Story:** As the owner, I want to take back a reservation, so that I can change a BOM or
lend its parts to another build.

#### Acceptance Criteria

1. WHEN a reserved revision is cancelled THE SYSTEM SHALL write, for every lot it reserves
   from, a `RELEASE` naming the revision of the whole quantity reserved there, lower the lot's
   reserved by it, and return the revision to draft.
2. WHEN a reservation is cancelled THE SYSTEM SHALL leave every lot's on hand as it was, so
   reserving and then cancelling leaves every balance and every unit as it started.
3. WHEN a revision cancelled back to draft is reserved again THE SYSTEM SHALL reserve it
   against the stock as it then stands, as a first reserve would.

### Requirement 5: Building

**User Story:** As the owner, I want building a revision to take exactly what I set aside, so
that the stock drops by what went onto the board and nothing else.

#### Acceptance Criteria

1. WHEN a reserved revision is built THE SYSTEM SHALL write, for every lot it reserves from, a
   `CONSUME` naming the revision of the whole quantity reserved there, lowering the lot's on
   hand and reserved by it, and set the revision built.
2. WHEN a revision is built THE SYSTEM SHALL consume exactly what was reserved for it, lot by
   lot, whatever was received, recounted or moved between the reserve and the build.
3. WHEN a part's category flags change after its stock was reserved or consumed THE SYSTEM
   SHALL cancel, build and dismantle what the ledger says the revision holds.

### Requirement 6: Dismantling

**User Story:** As the owner, I want dismantling a build to put its parts back in a drawer I
choose, so that a breadboard I pull apart returns to stock in one step.

#### Acceptance Criteria

1. WHEN a built revision is dismantled THE SYSTEM SHALL require a location of the workspace,
   and refuse with 422 a location the workspace doesn't hold, writing nothing.
2. WHEN a built revision is dismantled THE SYSTEM SHALL write, for each part its build
   consumed, one `RETURN` naming the revision of the whole quantity consumed, into the part's
   lot at the chosen location, created when absent, and set the revision dismantled.
3. WHEN a revision is built and then dismantled THE SYSTEM SHALL leave each part's total on
   hand as it was before the build, everything returned sitting at the chosen location.

### Requirement 7: Reserved stock stays reserved

**User Story:** As the owner, I want what I set aside for a build to still be there when I build
it, so that building never fails halfway.

#### Acceptance Criteria

1. WHEN a lot is recounted THE SYSTEM SHALL refuse a count below its reserved quantity with
   409, saying how many are reserved, and write nothing.
2. WHEN stock is moved out of a lot THE SYSTEM SHALL move at most its available stock, and
   refuse a larger quantity with 409, saying how many are reserved.
3. WHEN stock is received into a lot or moved into it THE SYSTEM SHALL add it to the lot's
   available stock, its reserved staying as it was.
4. WHEN any movement is applied THE SYSTEM SHALL keep its balance at 0 ≤ reserved ≤ on hand,
   with available equal to on hand less reserved.

### Requirement 8: The ledger and its projection

**User Story:** As the owner, I want every reservation, consumption and return in the ledger,
so that the stock history explains where each part went.

#### Acceptance Criteria

1. WHEN a `RESERVE`, `RELEASE`, `CONSUME` or `RETURN` is written THE SYSTEM SHALL name the
   revision that caused it, and have the database refuse one naming none, or a `RECEIVE`,
   `ADJUST` or `MOVE` naming one.
2. WHEN a movement is written THE SYSTEM SHALL store a positive change for `RESERVE` and
   `RETURN` and a negative one for `RELEASE` and `CONSUME`, and have the database refuse any
   other sign for them.
3. WHEN a movement is applied to its balance THE SYSTEM SHALL move on hand by `RECEIVE`,
   `ADJUST`, `MOVE`, `CONSUME` and `RETURN`, and reserved by `RESERVE`, `RELEASE` and
   `CONSUME`, each by the movement's change.
4. WHEN `wiredex stock rebuild` runs THE SYSTEM SHALL fold all seven kinds, in the ledger's
   order, into balances equal to the ones written as the movements happened, reserved
   included.
5. WHEN what a revision holds is needed THE SYSTEM SHALL compute it from the revision's
   movements: per lot the quantity it reserves, and per part the quantity its build consumed
   and hasn't returned.
6. WHEN a revision's holdings are computed THE SYSTEM SHALL find none while it is a draft or
   dismantled, reservations summing to the stocked needs it was reserved for while it is
   reserved, and consumption equal to them while it is built.

### Requirement 9: Deleting and forking

**User Story:** As the owner, I want a revision that holds stock kept until it gives the stock
back, so that no reservation or build is ever orphaned.

#### Acceptance Criteria

1. WHEN a reserved or built revision is deleted THE SYSTEM SHALL refuse it with 409, saying the
   reservation must be cancelled or the build dismantled first, and delete nothing.
2. WHEN a draft or a dismantled revision of a project with other revisions is deleted THE
   SYSTEM SHALL delete it and keep the movements that name it.
3. WHEN a project holding a reserved or built revision is deleted THE SYSTEM SHALL refuse it
   with 409 and delete nothing.
4. WHEN a revision in any status is forked THE SYSTEM SHALL create the fork as a draft holding
   no stock, and leave the source and what it holds as they were.

### Requirement 10: Reading builds and stock

**User Story:** As the owner, I want to see what each build holds and where my reserved parts
sit, so that I know which drawer to open before I pick up the soldering iron.

#### Acceptance Criteria

1. WHEN a revision's build is read THE SYSTEM SHALL answer its status, the transitions it
   allows, whether it can be deleted, and for each part it holds the part's name and facts, the
   quantity reserved in each location or consumed by the build, and its units.
2. WHEN a revision is read by its id alone THE SYSTEM SHALL answer its label, summary and
   status, with its project's id and name.
3. WHEN a part's stock is read THE SYSTEM SHALL answer on hand, reserved and available for each
   location that holds it, and in total.
4. WHEN a part's holdings are read THE SYSTEM SHALL answer each revision holding some of it,
   with how many it reserves and how many its build consumed.
5. WHEN the BOM of a revision that isn't a draft is read THE SYSTEM SHALL compute its shortage
   report against free stock as for a draft, which then answers what building it again would
   be missing.
6. WHEN a build, a part's stock or a part's holdings is read THE SYSTEM SHALL use a fixed number
   of queries, whatever the number of lots, units and revisions.

### Requirement 11: Workspace isolation

**User Story:** As the owner, I want a guest's builds kept inside their bench, so that lending a
demo account stays safe.

#### Acceptance Criteria

1. WHEN a transition runs THE SYSTEM SHALL read and write the projects, catalog and inventory
   rows it touches in one transaction under one workspace setting, so row-level security
   scopes all three.
2. WHEN a reserve names a unit, or a dismantle a location, of another workspace THE SYSTEM
   SHALL treat it as one the workspace doesn't hold.
3. WHEN a revision of another workspace is named by id THE SYSTEM SHALL answer 404, not 403.
4. WHEN a lifecycle or holdings request carries no valid session THE SYSTEM SHALL answer 401
   and touch nothing.
5. WHEN a transition carries no CSRF header THE SYSTEM SHALL answer 403 and touch nothing.

### Requirement 12: The demo workspace

**User Story:** As the owner, I want a guest's bench to open with a build already set aside, so
that a demo shows stock tied up in a build without any setup.

#### Acceptance Criteria

1. WHEN a demo bench's sample projects are restored THE SYSTEM SHALL reserve the sample
   *Greenhouse controller* revision `A` through the reserve use case, setting aside the bench's
   ESP32 board and the other parts its BOM needs.
2. WHEN a demo reset runs again, or a guest is invited, THE SYSTEM SHALL restore the same
   reservation, whatever the guest reserved, built, cancelled or dismantled.
3. WHEN the sample *Weather station* revisions are read after a restore THE SYSTEM SHALL report
   their ESP32 short, the bench's one board being reserved for the greenhouse.

### Requirement 13: Web

**User Story:** As the owner, I want to reserve, build and dismantle from the revision's page and
see reserved stock wherever stock is shown, so that the lifecycle is one click away and never a
surprise.

#### Acceptance Criteria

1. WHEN a revision is shown THE SYSTEM SHALL show its status and offer the transitions it
   allows: *Reserve parts* for a draft, *Build* and *Cancel reservation* for a reserved
   revision, and *Dismantle* for a built one.
2. WHEN *Reserve parts* is chosen THE SYSTEM SHALL list what will be reserved, name the
   consumables that won't be, and offer for each unit-tracked part a choice among its units in
   stock, automatic by default.
3. WHEN a reserve is refused THE SYSTEM SHALL show the refusal in the dialog, and for shortages
   each short and unknown part with its need, available stock and shortage, linking to the
   part's page.
4. WHEN *Build* or *Cancel reservation* is chosen THE SYSTEM SHALL ask first, in place.
5. WHEN *Dismantle* is chosen THE SYSTEM SHALL ask for the location with the location picker,
   saying that everything the build used returns there.
6. WHEN a reserved or built revision is shown THE SYSTEM SHALL show what it holds: each part
   with its quantity and the locations it is set aside in, or its quantity in the build, and
   each unit's code linking to the unit's page.
7. WHEN a revision's status changes THE SYSTEM SHALL show the new status in the revision panel,
   the project page's revisions and the project list, and refresh the BOM and every stock view
   on screen, in place and without a full reload.
8. WHEN a part's stock is shown THE SYSTEM SHALL show on hand, reserved and available for each
   location, the totals, and each revision holding the part, linking to it.
9. WHEN units are listed or a unit's page is shown THE SYSTEM SHALL show the reserved and in-use
   statuses with the revision they belong to, linking to it, and offer no move or retire for
   such a unit.
10. WHEN a recount or a move is entered THE SYSTEM SHALL refuse, before sending it, a count
    below the location's reserved quantity or a move above its available stock, saying so.
11. WHEN a revision that isn't a draft is shown THE SYSTEM SHALL title its shortage report as
    what building it again would be missing.
12. WHEN a revision that holds stock is shown THE SYSTEM SHALL offer deleting it unavailable,
    saying that cancelling the reservation or dismantling the build comes first.
13. WHEN a transition is refused THE SYSTEM SHALL show the refusal in the reader's language,
    from the code the API answers.
14. WHEN any lifecycle or stock screen is rendered THE SYSTEM SHALL take every string from an
    i18n key present in both `en.json` and `pt-BR.json`, and every colour from a theme token.
15. WHEN the lifecycle controls are operated by keyboard alone THE SYSTEM SHALL let every
    transition be chosen, confirmed and backed out of without a pointer, and expose every
    control with a role and an accessible name.
16. WHEN a lifecycle dialog, a build's holdings or a stock view is shown on a phone-width screen
    THE SYSTEM SHALL keep the page free of horizontal scrolling, a table wider than the screen
    scrolling inside its own box.

### Requirement 14: Non-functional

**User Story:** As the owner, I want the lifecycle to keep the architecture's lines and close the
phase cleanly, so that wiring, firmware and the dashboard build on it without rework.

#### Acceptance Criteria

1. WHEN the API is linted THE SYSTEM SHALL satisfy the import-linter contracts: `projects`
   imports no other module, and only the composition root binds inventory's stock operations
   and catalog's part reads to the projects unit of work.
2. WHEN migration `0018` is applied THE SYSTEM SHALL only widen a CHECK, add a nullable column,
   partial indexes and CHECKs that every row the previous release writes satisfies, and SHALL
   pass the up → down → up round trip.
3. WHEN a transition runs THE SYSTEM SHALL read the revision, its BOM, the parts, the lots with
   their balances and the units in a fixed number of queries whatever their number, and write
   one movement for each lot it touches.
4. WHEN routes or schemas change THE SYSTEM SHALL have `packages/api-client` regenerated, so
   CI's contract gate passes.
5. WHEN the API test suite runs THE SYSTEM SHALL keep total coverage at or above 90 %, and the
   web suite at or above 85 %.
6. WHEN the lifecycle, the balance projection over all seven kinds, the choice of lots and
   units, the holdings and the round trips are tested THE SYSTEM SHALL check them with
   Hypothesis.
7. WHEN the phase closes THE SYSTEM SHALL have the README's four `v0.5.0` lines ticked, and ADRs
   0001, 0002, 0003 and 0007, AGENTS.md and docs/architecture.md recording what the phase
   built, in one commit carrying `Release-As: 0.5.0`.
