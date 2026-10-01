# Requirements Document

## Introduction

Soft delete and the trash, the first of four specs in `v0.8.0` Everyday use. It delivers the
phase's roadmap line *Soft delete with a trash view*, and answers question 5 of
[docs/architecture.md](../../../docs/architecture.md) §10, *soft-delete everywhere, and hard
delete only from a trash view?*, for the four records that have a page of their own and lose the
most when deleted: a part ([01-catalog-foundation](../01-catalog-foundation/design.md)), a unit
([06-tracked-units](../06-tracked-units/design.md)), a project with its revisions
([08-projects-and-revisions](../08-projects-and-revisions/design.md)) and a firmware with its
versions ([13-firmware-versions](../13-firmware-versions/design.md)). Deleting one of them now
moves it to the trash. There it is out of the app as a deleted record is, until it is restored as
it was or deleted for good.

The next three specs build on it. [17-history](../17-history/requirements.md) records every
change, moves to and from the trash included; [18-dashboard](../18-dashboard/requirements.md)
shows recent activity from that history; [19-command-palette](../19-command-palette/requirements.md)
searches everything that isn't in the trash. [design.md](design.md) answers these.

Acceptance criteria use EARS: `WHEN <condition> THE SYSTEM SHALL <behaviour>`. Every criterion
acts inside the caller's workspace.

Owner decisions (2026-09-27) that bind every spec and reach this one: one PR per spec with
auto-merge; the release PR waits for the phase's last spec (19-command-palette), and only the owner
merges it, since merging it deploys to production. This spec carries no `Release-As` footer.

Decisions taken without the owner (2026-10-01), for the owner to review:

1. **The trash takes parts, units, projects and firmware**, each with what it holds (a part's
   pinout, a project's revisions with their BOMs and netlists, a firmware's versions, files and
   links). Why: they are the records with a page and a Delete button, each one aggregate whose
   contents go with it.
2. **Revisions, firmware versions, categories, locations, attachments and the rows edited inside a
   page** (BOM lines, nets, pins, source files, flashes, links) **are still deleted at once.** Why:
   each is part of a bigger record, or structure deletable only while empty; 17-history records
   their removal, and the first trash stays one filter per module.
3. **In the trash a record is absent everywhere**, as a deleted one is: lists, searches, pickers,
   counts, its own page (404) and every other module's lookups. Why: the rest of the app already
   handles a missing record, where a second "hidden but there" state would reach every screen.
4. **Moving to the trash refuses what deleting refused** (a part a BOM names, a project with a
   reserved or built revision, a firmware a flash names, a unit not retired), **and a BOM in a
   project in the trash still names its parts.** Why: whatever reaches the trash can be restored
   whole, and deleted for good without breaking anything.
5. **A record in the trash keeps its name, MPN, serial and MAC.** The unique indexes stay as they
   are, and a refusal for a taken name or MPN says its holder is in the trash; a taken serial or
   MAC keeps 06's sentence, *another unit already has it*, which stays true. Why: restoring never
   meets a clash, and rolling the release back only brings trashed records back, never a
   duplicate.
6. **Deleting for good is today's delete, from the trash only, and checks nothing more.** Why:
   nothing new can point at a record while it is absent, so what deleting checked was checked when
   the record went to the trash.
7. **Nothing leaves the trash on its own; the owner empties it.** Why: a purge timer is a change on
   the server, and one owner's trash stays small.
8. **A category whose parts are all in the trash still can't be deleted, and says so.** Why: a part
   in the trash keeps its category to be restored into, and the database's key holds it.
9. **The nightly files prune keeps the attachments of a record in the trash**, and sweeps them once
   it is deleted for good. Why: restoring a part brings its datasheets back.
10. **A `trash` module lists the trash across modules and hands each restore or delete for good to
    the module that owns the record.** Why: one list with one cursor and one set of routes, while
    each module keeps its own rules and none imports another.
11. **The trash is read newest first, 50 at a time by default and at most 100, with a cursor.**
    Why: every list has a limit, and the cursor stays right while things are restored meanwhile.
12. **Emptying the trash deletes everything in it for good, one module at a time.** Why: one action
    for the usual clean-up, each module's share in one transaction.
13. **Delete buttons say *Move to trash*, and the trash has its own page, last in the main
    navigation.** Why: the word says what happens, and the trash is one click from anywhere.

## Glossary

- **The owner**: the single real user. A guest acts the same way inside their demo bench.
- **Record**: in this spec, a part, a unit, a project or a firmware.
- **Kind**: which of the four a record is.
- **Contents**: what a record holds and deletes with it: a part's pinout; a project's revisions,
  their BOM lines, designators, nets and pins; a firmware's versions, their source files and its
  links to revisions.
- **Trash**: the workspace's records moved there and not yet restored or deleted for good.
- **Move to the trash**: what deleting a record does from this spec on.
- **Restore**: bring a record back from the trash, as it was.
- **Delete for good**: remove a record in the trash, with its contents, as deleting did before this
  spec.
- **Absent**: answered as a record that doesn't exist: left out of every list and lookup, and 404
  by id.

## Requirements

### Requirement 1: Moving a record to the trash

**User Story:** As the owner, I want a deleted record kept for a while, so that a slip of the mouse
never costs me a project.

#### Acceptance Criteria

1. WHEN a part, unit, project or firmware is deleted THE SYSTEM SHALL move it to the trash with
   its contents, recording when, and answer 204.
2. WHEN a part a bill of materials names is deleted THE SYSTEM SHALL refuse it with 409 as before,
   counting the bills of materials of projects in the trash, and mark each of those as in the
   trash in the refusal.
3. WHEN a project with a reserved or built revision, a firmware whose versions a flash names, or a
   unit that isn't retired is deleted THE SYSTEM SHALL refuse it as before and change nothing.
4. WHEN a record already in the trash, or not in the workspace, is deleted THE SYSTEM SHALL answer
   404.
5. WHEN a record is moved to the trash while another request changes it or what it holds THE
   SYSTEM SHALL apply them one at a time, so nothing is reserved, flashed or added to a record
   once it is in the trash.

### Requirement 2: Out of the app while in the trash

**User Story:** As the owner, I want a record in the trash out of my way, so that lists and pickers
show only what I use.

#### Acceptance Criteria

1. WHEN a record is in the trash THE SYSTEM SHALL leave it out of every list, search, picker and
   count, and answer 404 for it and its contents by id.
2. WHEN a record in the trash, or one of its contents, is named by a write THE SYSTEM SHALL answer
   as for a record that doesn't exist: no stock is received into a part in the trash, no BOM line
   names it, no unit in the trash is moved, relabelled or flashed, no revision of a project in the
   trash is edited, reserved or forked, no firmware in the trash is linked or versioned, and no
   file is attached to any of them.
3. WHEN another module looks up a record in the trash THE SYSTEM SHALL answer it as absent: a BOM
   shows its part as unknown, a firmware leaves out the revisions of a project in the trash, a
   unit's log leaves out a revision of a project in the trash, and a firmware's boards leave out a
   unit in the trash.
4. WHEN a revision of a project that isn't in the trash is forked THE SYSTEM SHALL copy only the
   links of firmware that isn't in the trash.

### Requirement 3: Names kept while in the trash

**User Story:** As the owner, I want a record in the trash to keep its name, so that restoring it
never collides with something new.

#### Acceptance Criteria

1. WHEN a project or a firmware is created or renamed with a name a record in the trash holds,
   ignoring case, THE SYSTEM SHALL refuse it with 409, saying the holder is in the trash.
2. WHEN a part is defined or edited with the manufacturer and MPN of a part in the trash THE SYSTEM
   SHALL refuse it with 409, saying the holder is in the trash.
3. WHEN quick-add or a sheet import names the manufacturer and MPN of a part in the trash THE
   SYSTEM SHALL mark the row with a problem on the MPN saying the part is in the trash, and write
   nothing for it.
4. WHEN a unit is received or relabelled with a serial or a MAC a unit in the trash holds THE SYSTEM
   SHALL refuse it as for any taken serial or MAC.

### Requirement 4: The trash

**User Story:** As the owner, I want one place listing what I deleted, so that I find a record
again without remembering where it lived.

#### Acceptance Criteria

1. WHEN the trash is read THE SYSTEM SHALL answer its records newest first by when they were moved
   there, each with its kind, id, name (a unit's is its code), a detail (a part's MPN, a unit's
   part, a firmware's target) and when it was moved.
2. WHEN the trash is read with a limit THE SYSTEM SHALL answer at most that many records, 50 when
   none is given, refusing a limit below 1 or above 100 with 422.
3. WHEN more records are in the trash than one read answers THE SYSTEM SHALL answer a cursor that
   reads the next ones, in the same order, even when records were restored or deleted meanwhile.
4. WHEN a cursor the API didn't give is sent THE SYSTEM SHALL refuse it with 422.
5. WHEN the trash is empty THE SYSTEM SHALL answer an empty list with 200.

### Requirement 5: Restoring a record

**User Story:** As the owner, I want to bring a deleted record back exactly as it was, so that the
trash undoes the delete.

#### Acceptance Criteria

1. WHEN a record in the trash is restored THE SYSTEM SHALL put it back with its contents and every
   value it had, and answer 204.
2. WHEN a restored record is read THE SYSTEM SHALL answer it in every list, search and lookup it
   was in before.
3. WHEN a record that isn't in the trash, or not in the workspace, is restored THE SYSTEM SHALL
   answer 404.
4. WHEN a record is restored while another request deletes it for good THE SYSTEM SHALL apply them
   one at a time, so it is either back or gone, never both.

### Requirement 6: Deleting for good

**User Story:** As the owner, I want to remove what I'm sure about, so that the trash only holds
what I might still want.

#### Acceptance Criteria

1. WHEN a record in the trash is deleted for good THE SYSTEM SHALL delete it with its contents, as
   deleting did before this spec, and answer 204.
2. WHEN a record that isn't in the trash, or not in the workspace, is deleted for good THE SYSTEM
   SHALL answer 404 and delete nothing.
3. WHEN a unit in the trash is deleted for good THE SYSTEM SHALL keep its movements and its
   flashes, as deleting a unit did before.
4. WHEN the trash is emptied THE SYSTEM SHALL delete every record in it for good, and answer 204.

### Requirement 7: What a record in the trash keeps

**User Story:** As the owner, I want a record in the trash to keep what it needs to come back, so
that restoring it never finds a piece missing.

#### Acceptance Criteria

1. WHEN a category is deleted while only parts in the trash are filed under it THE SYSTEM SHALL
   refuse it with 409, saying its parts are in the trash.
2. WHEN the nightly files prune runs THE SYSTEM SHALL keep the attachments of a part, project or
   revision whose record is in the trash, and remove them once it is deleted for good.
3. WHEN a demo bench is reset THE SYSTEM SHALL empty its trash with everything else.

### Requirement 8: Workspace isolation

**User Story:** As the owner, I want a guest's trash kept inside their bench, so that lending a demo
account stays safe.

#### Acceptance Criteria

1. WHEN the trash is read THE SYSTEM SHALL answer only the caller's workspace's records, row-level
   security included.
2. WHEN a record of another workspace is restored or deleted for good THE SYSTEM SHALL answer 404
   and change nothing.
3. WHEN a trash request carries no valid session THE SYSTEM SHALL answer 401 and touch nothing.
4. WHEN a trash write carries no CSRF header THE SYSTEM SHALL answer 403 and touch nothing.

### Requirement 9: Web

**User Story:** As the owner, I want the trash one click away, so that undoing a delete takes
seconds.

#### Acceptance Criteria

1. WHEN a part, unit, project or firmware page offers deleting THE SYSTEM SHALL label it *Move to
   trash* and ask first, in place, saying it can be restored from the trash.
2. WHEN the signed-in app is shown THE SYSTEM SHALL offer *Trash* in the main navigation, last.
3. WHEN the trash page is opened THE SYSTEM SHALL list its records newest first with their kind,
   name, detail and when they were moved, more on request, or say the trash is empty.
4. WHEN a record is restored in the browser THE SYSTEM SHALL take it off the list and say it is
   back, with a link to its page.
5. WHEN a record is deleted for good in the browser THE SYSTEM SHALL ask first, in its row, saying
   it can't be undone.
6. WHEN the trash is emptied in the browser THE SYSTEM SHALL ask first, saying it can't be undone.
7. WHEN a record moves to or from the trash THE SYSTEM SHALL refresh the trash, the lists and the
   pages it appears in, without a full reload.
8. WHEN a trash screen is rendered THE SYSTEM SHALL take every string from an i18n key present in
   both `en.json` and `pt-BR.json`, and every colour from a theme token.
9. WHEN those screens are operated by keyboard alone THE SYSTEM SHALL reach every control, each with
   a role and an accessible name.
10. WHEN they are shown on a phone-width screen THE SYSTEM SHALL keep the page free of horizontal
    scrolling, a wide table scrolling inside its own box.

### Requirement 10: Non-functional

**User Story:** As the owner, I want the trash to keep the architecture's lines, so that history
and the palette build on it without rework.

#### Acceptance Criteria

1. WHEN the API is linted THE SYSTEM SHALL satisfy the import-linter contracts with `trash` as a
   module of its own that imports no other module, only the composition root connecting it to
   catalog, inventory, projects and firmware.
2. WHEN migration `0022` is applied THE SYSTEM SHALL only add columns and indexes, in a migration
   that passes the up → down → up round trip.
3. WHEN the trash is read THE SYSTEM SHALL use a fixed number of queries, whatever the number of
   records.
4. WHEN routes or schemas change THE SYSTEM SHALL have `packages/api-client` regenerated, so CI's
   contract gate passes.
5. WHEN the API test suite runs THE SYSTEM SHALL keep total coverage at or above 90 %, and the web
   suite at or above 85 %.
6. WHEN reading the trash page by page is tested THE SYSTEM SHALL check with Hypothesis that every
   record is read once, newest first, whatever the kinds and times.

## Out of scope

- Revisions, firmware versions, categories, locations and attachments in the trash (decision 2).
- Emptying the trash on a timer (decision 7).
- Opening a record's page while it is in the trash, or editing it there.
- Who moved a record to the trash: 17-history records it.
- Undoing a move to the trash from a notice on the list it left: the trash is one click away.
