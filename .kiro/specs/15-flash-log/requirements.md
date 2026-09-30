# Requirements Document

## Introduction

The flash log, the last of three specs in `v0.7.0` Firmware. It delivers the phase's roadmap line
*Flash log per unit, with the current version shown on the unit page*, and closes the phase. It
builds the log [ADR 0006](../../../docs/adr/0006-firmware-snapshots.md) decided, *a deployment log
records unit ← version flashes with a date and notes; a unit's current firmware is its latest
deployment*, calling a deployment a *flash*, as the roadmap and the README do. It reads the link
[10-build-lifecycle](../10-build-lifecycle/design.md) gave every tracked unit of
[06-tracked-units](../06-tracked-units/design.md), the revision a reserved or in-use unit belongs
to, and keeps the versions of [13-firmware-versions](../13-firmware-versions/design.md) that a
board's log names from being deleted. With it, the README's question *which firmware version is
running on the greenhouse ESP32 right now?* takes one look. [design.md](design.md) answers these.

Acceptance criteria use EARS: `WHEN <condition> THE SYSTEM SHALL <behaviour>`. Every criterion
acts inside the caller's workspace.

Owner decisions (2026-09-27) that bind every spec and reach this one: one PR per spec with
auto-merge; the release PR waits for the phase's last spec, this one, and only the owner merges it,
which deploys to production. This spec's phase-closing documentation task carries the
`Release-As: 0.7.0` footer. A change history waits for `v0.8.0` (2026-09-26).

Owner decision (2026-09-26) that reaches this spec: every microcontroller board is a unit, by its
category's *tracked individually* flag (docs/architecture.md §10, question 1), so every board that
can be flashed has a unit page to log it on.

## Glossary

- **The owner**: the single real user. A guest acts the same way inside their demo bench.
- **Unit**: 06's individually tracked item: a board with a short code (`WX-U-0042`) and optionally
  a serial and a MAC.
- **Held**: a unit reserved for, or built into, a revision (10); a held unit names that revision.
- **Retired**: a unit out of stock for good, damaged or lost (06).
- **Flash**: one entry of the flash log: a released version written onto a unit, when that was
  done, and notes. ADR 0006's deployment.
- **Flash log**: a unit's flashes, newest first.
- **Current version**: the version of a unit's newest flash, by when it was flashed.
- **Newer release**: a released version of the same firmware above a unit's current version.
- **Board**: in this spec, a unit whose current version is one of a given firmware's.

## Requirements

### Requirement 1: Logging a flash

**User Story:** As the owner, I want to write down each time I flash a board, so that the code on
every board is on record.

#### Acceptance Criteria

1. WHEN a flash is logged THE SYSTEM SHALL record the unit, the released version flashed, when it
   was flashed and the notes given.
2. WHEN a flash is logged without a time THE SYSTEM SHALL record it as flashed now.
3. WHEN a flash is logged with a time THE SYSTEM SHALL record that time, even one before the
   version was released.
4. WHEN a flash's time is more than five minutes in the future THE SYSTEM SHALL refuse it with 422
   on the time.
5. WHEN a flash names a draft THE SYSTEM SHALL refuse it with 409, since a draft can still change.
6. WHEN a flash names a retired unit THE SYSTEM SHALL refuse it with 409.
7. WHEN a flash is logged on a held unit THE SYSTEM SHALL record the revision holding it then, so
   the entry keeps naming that revision after the build is cancelled or dismantled.
8. WHEN a flash is logged THE SYSTEM SHALL record the unit's short code with it, so the entry still
   names the board after the unit is deleted.
9. WHEN a flash's notes are given THE SYSTEM SHALL trim them and collapse their whitespace, read
   blank notes as none, and refuse notes longer than 500 characters or holding a control character
   with 422 on the notes.
10. WHEN a flash names a unit or a version that isn't in the workspace THE SYSTEM SHALL answer 404
    and write nothing.
11. WHEN a unit is flashed while another request retires or deletes it, or deletes the version, THE
    SYSTEM SHALL apply them one at a time, so no flash is recorded on a retired unit or for a
    version that is gone.

### Requirement 2: A unit's flash log and current version

**User Story:** As the owner, I want a board's page to say what it runs, so that "which version is
on the greenhouse ESP32?" takes one look.

#### Acceptance Criteria

1. WHEN a unit's flash log is read THE SYSTEM SHALL answer its flashes newest first, by when they
   were flashed and then by when they were logged, each with its firmware, version, time and notes,
   and the revision it recorded while that revision is still in the workspace.
2. WHEN a unit's flash log is read THE SYSTEM SHALL answer its current version, the version of its
   newest flash by flash time and then by logging, or none when it has no flash.
3. WHEN a unit's current version has a newer release THE SYSTEM SHALL answer the firmware's highest
   released version with it.
4. WHEN a retired unit's flash log is read THE SYSTEM SHALL answer it as any unit's, and say the unit
   is retired.
5. WHEN a unit that isn't in the workspace has its flash log read THE SYSTEM SHALL answer 404.

### Requirement 3: Correcting the log

**User Story:** As the owner, I want to remove an entry I logged by mistake, so that the log says
what is really on the board.

#### Acceptance Criteria

1. WHEN a flash is removed THE SYSTEM SHALL delete it, whatever its unit's status, the flashes of a
   unit no longer in the workspace included.
2. WHEN a flash has been removed THE SYSTEM SHALL answer its unit's current version from the flashes
   left.
3. WHEN a flash that isn't in the workspace is removed THE SYSTEM SHALL answer 404.

### Requirement 4: The boards a firmware runs on

**User Story:** As the owner, I want a firmware's page to list the boards running it, so that I see
which boards still run an older version.

#### Acceptance Criteria

1. WHEN a firmware's boards are read THE SYSTEM SHALL answer every unit whose current version is one
   of the firmware's, by short code, each with that version, when it was flashed, the revision
   holding the unit now, and the newer release when there is one.
2. WHEN a unit is retired, or no longer in the workspace, THE SYSTEM SHALL leave it out of every
   firmware's boards.
3. WHEN a firmware that isn't in the workspace has its boards read THE SYSTEM SHALL answer 404.

### Requirement 5: Keeping the record

**User Story:** As the owner, I want a version a board's log names to stay, so that no entry ever
points at nothing.

#### Acceptance Criteria

1. WHEN a version a flash names is deleted THE SYSTEM SHALL refuse it with 409 and delete nothing,
   answering each of those flashes with its unit's code and whether the unit is still in the
   workspace.
2. WHEN a firmware is deleted and a flash names one of its versions THE SYSTEM SHALL refuse it with
   409 and delete nothing, answering those flashes as 5.1 does.
3. WHEN a version no flash names is deleted THE SYSTEM SHALL delete it as 13 does.
4. WHEN a unit is deleted THE SYSTEM SHALL keep its flashes, as the ledger keeps its movements.

### Requirement 6: Workspace isolation

**User Story:** As the owner, I want a guest's flash log kept inside their bench, so that lending a
demo account stays safe.

#### Acceptance Criteria

1. WHEN the application connects as its non-owner database role THE SYSTEM SHALL have row-level
   security deny reads and writes of another workspace's flashes.
2. WHEN a unit, version, firmware or flash of another workspace is named by id THE SYSTEM SHALL
   answer 404, not 403.
3. WHEN a flash is written THE SYSTEM SHALL have the database refuse it unless its version is in the
   same workspace.
4. WHEN a flash request carries no valid session THE SYSTEM SHALL answer 401 and touch nothing.
5. WHEN a flash write carries no CSRF header THE SYSTEM SHALL answer 403 and touch nothing.

### Requirement 7: The demo workspace

**User Story:** As the owner, I want a guest's bench to show boards with firmware on them, so that a
demo answers "what runs on this board?" before the guest logs anything.

#### Acceptance Criteria

1. WHEN a demo bench is restored THE SYSTEM SHALL log the sample ESP32 board, reserved for
   *Greenhouse controller* `A`, as flashed with *Greenhouse controller* `0.1.0` a day before the
   restore, and the sample Pico as flashed with *Pico blink* `1.0.0` two days before, so the Pico's
   page shows `1.1.0` as a newer release.
2. WHEN the sample flashes are restored THE SYSTEM SHALL log them through the flash use case, after
   the sample firmware.
3. WHEN a demo reset runs again THE SYSTEM SHALL remove the flashes a guest logged and put the
   samples back.

### Requirement 8: Web

**User Story:** As the owner, I want the log where I look at a board and where I copy the code, so
that writing a flash down takes a few seconds.

#### Acceptance Criteria

1. WHEN a unit's page is shown THE SYSTEM SHALL show its current firmware and version, when it was
   flashed and the newer release when there is one, or say that none is logged, and its flash log
   below.
2. WHEN *Log a flash* is chosen on a unit's page THE SYSTEM SHALL offer the workspace's firmware,
   those running on the revision holding the unit first, then the chosen firmware's released
   versions highest first, a time defaulting to now, and notes.
3. WHEN *Log a flash* is chosen on a released version THE SYSTEM SHALL offer the workspace's units,
   found by short code, serial or MAC, a retired unit shown as unavailable, then the time and notes.
4. WHEN a retired unit's page is shown THE SYSTEM SHALL show its flash log without *Log a flash*,
   saying why.
5. WHEN a flash is removed in the browser THE SYSTEM SHALL ask first, in its row.
6. WHEN a firmware's page is shown THE SYSTEM SHALL list the boards running it, each linking to its
   unit, with its version, when it was flashed and where it is now, and a newer release in words
   and an icon, not colour alone.
7. WHEN a version or a firmware can't be deleted because flashes name it THE SYSTEM SHALL list those
   flashes, each unit's code linking to its page while the unit is in the workspace, and offer to
   remove each flash there, so even a deleted unit's entries can be cleared.
8. WHEN a flash is logged or removed THE SYSTEM SHALL refresh the unit's page, the firmware's boards
   and the version's panel in place, without a full reload.
9. WHEN any flash screen is rendered THE SYSTEM SHALL take every string from an i18n key present in
   both `en.json` and `pt-BR.json`, and every colour from a theme token.
10. WHEN those screens are operated by keyboard alone THE SYSTEM SHALL reach every control, each with
    a role and an accessible name.
11. WHEN they are shown on a phone-width screen THE SYSTEM SHALL keep the page free of horizontal
    scrolling, a wide table scrolling inside its own box.

### Requirement 9: Non-functional

**User Story:** As the owner, I want the flash log to keep the architecture's lines and close the
phase cleanly, so that the dashboard builds on it without rework.

#### Acceptance Criteria

1. WHEN the API is linted THE SYSTEM SHALL satisfy the import-linter contracts: `firmware` imports no
   other module, and only the composition root connects it to `inventory`.
2. WHEN migration `0021` is applied THE SYSTEM SHALL only add a table, in a migration that passes
   the up → down → up round trip.
3. WHEN a unit's flash log or a firmware's boards are read THE SYSTEM SHALL use a fixed number of
   queries, whatever the numbers of flashes, units and versions.
4. WHEN routes or schemas change THE SYSTEM SHALL have `packages/api-client` regenerated, so CI's
   contract gate passes.
5. WHEN the API test suite runs THE SYSTEM SHALL keep total coverage at or above 90 %, and the web
   suite at or above 85 %.
6. WHEN the current version, the newer release and a firmware's boards are tested THE SYSTEM SHALL
   check them with Hypothesis.
7. WHEN the phase closes THE SYSTEM SHALL have the README's four `v0.7.0` lines ticked, and ADR 0006,
   ADR 0003, ADR 0001 and docs/architecture.md recording what the phase built, in one commit
   carrying `Release-As: 0.7.0`.

## Out of scope

- Flashing from the browser (WebSerial or esptool-js, *Later*), and reading what a board runs from
  the board itself.
- Editing a flash: an entry is removed and logged again.
- A board's firmware on the revision page or in the units list, and outdated boards on the dashboard
  (18-dashboard, `v0.8.0`).
- Checking that a firmware's board target matches the unit's part.
- A history of the log (`v0.8.0`).
