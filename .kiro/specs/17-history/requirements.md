# Requirements Document

## Introduction

History, the second of four specs in `v0.8.0` Everyday use. It delivers the phase's roadmap line
*History for everything: every change with who, when and before/after, a timeline on each page, a
workspace activity feed, and restoring a past version (a restore is itself a new change, so
nothing is lost). Data created before this release starts its history here.*

It builds on [16-soft-delete-and-trash](../16-soft-delete-and-trash/requirements.md): a record
moved to the trash and back is a change like any other, and a move to the trash is restored from
the trash. [18-dashboard](../18-dashboard/requirements.md) shows the newest changes of this
spec's feed. [design.md](design.md) answers these.

Acceptance criteria use EARS: `WHEN <condition> THE SYSTEM SHALL <behaviour>`. Every criterion
acts inside the caller's workspace.

Owner decisions (2026-09-27) that bind every spec and reach this one: one PR per spec with
auto-merge; the release PR waits for the phase's last spec (19-command-palette), and only the owner
merges it, since merging it deploys to production. This spec carries no `Release-As` footer.

Decisions taken without the owner (2026-10-01), for the owner to review:

1. **The database records history: one trigger function on every tracked table, attached by a
   `track_history(table)` migration helper.** Each transaction names its user and an optional
   reason next to its workspace, as `app.workspace_id` is named today. Why: no write path can
   forget to record, a write that rolls back records nothing, and an API rolled back to the
   previous release still writes through the triggers.
2. **What is tracked: parts with their pins, units with their flashes, projects with their
   revisions, BOM lines, designators, nets and net pins, firmware with its versions, source files
   and runs-on links, attachments, and categories with their fields and locations.** The stock
   ledger, files and the identity tables are not. Why: those are the records a person edits; the
   ledger is already the history of stock (ADR 0002), a file is reached through its attachment,
   and accounts and sessions hold secrets and are not workspace data.
3. **A change is one transaction's writes to one record and what it holds.** Saving a pinout,
   adding a BOM line or moving a project to the trash is one change, listing each row it wrote.
   Why: a save is one thing to read, not a row per pin.
4. **Who is the signed-in user, by the name they had at the time; what Wiredex does itself (the
   nightly jobs and the command line) reads as Wiredex.** Why: the name kept with the change
   still reads right once a guest's account is gone.
5. **Before and after are whole-row snapshots. The API answers the fields that changed, each as
   text, a long value shortened to 300 characters; a reference to another record shows as its
   id.** Why: snapshots keep everything for later, while a page shows what a person reads.
6. **Restoring brings a part's, unit's, project's or firmware's own fields back as they were
   just before a chosen change, through the module's own edit, so its rules still apply.** A
   part's are its category, name, manufacturer, MPN, package and values; a unit's its serial and
   MAC; a project's its name, description and tags; a firmware's its name, target, framework and
   description. A move to the trash is restored from the trash. The restore is a new change,
   marked as one. Why: the module refuses what it would refuse from the form (a taken name, a
   value the schema no longer takes), and nothing is overwritten unseen.
7. **What is deleted for good, or deleted at once (a revision, a BOM line, a net), stays in
   history as it last was, and is not re-created from there.** Why: re-creating rows would go
   around each module's rules and keys; the trash is where a record comes back from.
8. **History is not backfilled: a record's history starts with its first change after the
   upgrade, and the page says so.** Why: nothing was recorded to backfill from, and a made-up
   "created" entry would claim a time and an author nobody knows.
9. **History is kept for good in the owner's workspace; a demo bench's is wiped when the bench
   is seeded and at its nightly reset.** Why: the owner's history is the point of this spec,
   while a guest's bench starts clean each day.
10. **The API's database role can read and delete history, never write or change it.** Why:
    like the stock ledger (ADR 0002), the database refuses a forged or edited change even from a
    bug; deleting is what a demo reset needs.
11. **The feed and a timeline are read newest first, 50 changes at a time by default and at most
    100, with a cursor; a change lists at most 20 of its row changes and says how many more.**
    Why: every list has a limit.
12. **The timeline is a *History* section on the part, unit, project and firmware pages, closed
    until opened; the feed is an *Activity* page in the main navigation, before *Trash*.
    Categories and locations show in the feed only.** Why: the record pages load as fast as
    before, and the trash stays last (16's decision 13).

## Glossary

- **The owner**: the single real user. A guest acts the same way inside their demo bench.
- **Tracked row**: a row of a table decision 2 names.
- **Record**: the part, unit, project, firmware, category or location a tracked row belongs to:
  itself, or the record that holds it (a pin's part, a net's project).
- **Change**: what one transaction wrote to one record and what it holds, with when, who and why.
- **Row change**: one tracked row inserted, updated or deleted within a change, with its before and
  after snapshots.
- **Feed**: every change of the workspace, newest first.
- **Timeline**: the changes of one record, newest first.
- **Restore**: put a record's own fields back as they were just before a change.

## Requirements

### Requirement 1: Recording every change

**User Story:** As the owner, I want every change kept with who, when and what, so that I can tell
how a record got to where it is.

#### Acceptance Criteria

1. WHEN a tracked row is inserted, updated or deleted THE SYSTEM SHALL record a row change with the
   operation, the row's snapshots before and after, and the fields that changed, in the same
   transaction as the write.
2. WHEN tracked rows are written in one transaction THE SYSTEM SHALL group them into one change per
   record, with the time, the signed-in user's id and name, and the reason the transaction named.
3. WHEN an update changes no field, or only when the row was last updated, THE SYSTEM SHALL record
   nothing for it.
4. WHEN a write is refused or its transaction rolls back THE SYSTEM SHALL keep no change of it.
5. WHEN rows are deleted because their record is deleted in the same statement (a part's pins,
   a project's revisions and lines) THE SYSTEM SHALL record the record's deletion and not each of
   its rows.
6. WHEN Wiredex writes without a signed-in user (a nightly job, the command line, a migration)
   THE SYSTEM SHALL record the change with no user.
7. WHEN a record is renamed THE SYSTEM SHALL keep each change with the record's name as it was
   then.

### Requirement 2: The activity feed

**User Story:** As the owner, I want one feed of everything that changed, so that I can see what
happened on my bench.

#### Acceptance Criteria

1. WHEN the feed is read THE SYSTEM SHALL answer the workspace's changes newest first, each with
   its time, its user's name or none, its reason, its record's kind, id and name, what happened
   to the record (created, edited, moved to the trash, restored from the trash, restored to an
   earlier version, deleted) and its row changes.
2. WHEN a row change is answered THE SYSTEM SHALL give its kind, its operation, a label from its
   snapshot, and each changed field's name with its value before and after as text, a value
   longer than 300 characters shortened.
3. WHEN a change holds more than 20 row changes THE SYSTEM SHALL answer the first 20 and how many
   more there are.
4. WHEN the feed is read with a limit THE SYSTEM SHALL answer at most that many changes, 50 when
   none is given, refusing a limit below 1 or above 100 with 422.
5. WHEN more changes exist than one read answers THE SYSTEM SHALL answer a cursor that reads the
   next ones in the same order, and refuse with 422 a cursor the API didn't give.
6. WHEN a change can be restored THE SYSTEM SHALL say so in it.

### Requirement 3: A record's timeline

**User Story:** As the owner, I want a record's own history on its page, so that I can see what
happened to the part in front of me.

#### Acceptance Criteria

1. WHEN the timeline of a part, unit, project or firmware is read THE SYSTEM SHALL answer its
   changes newest first, those to what it holds included, in the feed's shape, limits and cursor.
2. WHEN the timeline of a record that isn't in the workspace, or is in the trash, is read THE
   SYSTEM SHALL answer 404.
3. WHEN a record has no change recorded THE SYSTEM SHALL answer an empty timeline with 200.

### Requirement 4: Restoring a past version

**User Story:** As the owner, I want to put a record back as it was before a change, so that a
bad edit costs me one click.

#### Acceptance Criteria

1. WHEN a change that edited a part's, unit's, project's or firmware's own fields is restored THE
   SYSTEM SHALL put those fields back as they were just before the change, through the module's
   own edit, and answer 204.
2. WHEN a restore is saved THE SYSTEM SHALL record it as a new change of the record, marked as a
   restore, so the version it replaced stays in history.
3. WHEN a change that moved a record to the trash is restored THE SYSTEM SHALL restore the record
   from the trash, and answer 409 when it is no longer there.
4. WHEN the module refuses the fields being put back (a name another record now holds, a value
   the category's schema no longer takes, a category since deleted) THE SYSTEM SHALL answer 409
   with the module's sentence and change nothing.
5. WHEN a change that can't be restored is restored (one that created or deleted its record,
   changed only what it holds, or belongs to a category or a location) THE SYSTEM SHALL answer 409.
6. WHEN a change of another workspace, or one that doesn't exist, is restored THE SYSTEM SHALL
   answer 404.

### Requirement 5: What history keeps

**User Story:** As the owner, I want history I can trust, so that it tells me what really happened.

#### Acceptance Criteria

1. WHEN the API's database role writes or updates a change or a row change directly THE SYSTEM
   SHALL refuse it.
2. WHEN a record is deleted for good THE SYSTEM SHALL keep its changes, the deletion included.
3. WHEN this release is installed THE SYSTEM SHALL start every record's history empty, and its
   first change after that holds the record as it was before it.
4. WHEN a demo bench is seeded or reset THE SYSTEM SHALL leave its history empty.

### Requirement 6: Workspace isolation

**User Story:** As the owner, I want a guest's history kept inside their bench, so that lending a
demo account stays safe.

#### Acceptance Criteria

1. WHEN the feed or a timeline is read THE SYSTEM SHALL answer only the caller's workspace's
   changes, row-level security included.
2. WHEN a history request carries no valid session THE SYSTEM SHALL answer 401 and touch nothing.
3. WHEN a restore carries no CSRF header THE SYSTEM SHALL answer 403 and change nothing.

### Requirement 7: Web

**User Story:** As the owner, I want history one click away from wherever I am, so that I use it.

#### Acceptance Criteria

1. WHEN the signed-in app is shown THE SYSTEM SHALL offer *Activity* in the main navigation,
   before *Trash*.
2. WHEN the activity page is opened THE SYSTEM SHALL list the changes newest first, each with its
   time, who made it, what happened to which record, linking to the record's page, and its row
   changes with their fields before and after, more on request.
3. WHEN a part, unit, project or firmware page is shown THE SYSTEM SHALL offer a *History* section
   that, once opened, lists the record's changes the same way.
4. WHEN a change can be restored THE SYSTEM SHALL offer *Restore the version before this change*,
   ask first in place, and once restored refresh the record's page, its lists, the trash and
   history without a full reload.
5. WHEN a restore is refused THE SYSTEM SHALL say why beside the change.
6. WHEN a timeline or the feed has nothing older THE SYSTEM SHALL say that history starts with this
   release.
7. WHEN a history screen is rendered THE SYSTEM SHALL take every string from an i18n key present in
   both `en.json` and `pt-BR.json`, and every colour from a theme token.
8. WHEN those screens are operated by keyboard alone THE SYSTEM SHALL reach every control, each with
   a role and an accessible name.
9. WHEN they are shown on a phone-width screen THE SYSTEM SHALL keep the page free of horizontal
   scrolling.

### Requirement 8: Non-functional

**User Story:** As the owner, I want history to keep the architecture's lines, so that the
dashboard builds on it.

#### Acceptance Criteria

1. WHEN the API is linted THE SYSTEM SHALL satisfy the import-linter contracts with `history` as a
   module of its own that imports no other module.
2. WHEN migration `0023` is applied THE SYSTEM SHALL only add tables, indexes, functions and
   triggers, isolate the new tables by workspace, and pass the up → down → up round trip.
3. WHEN the feed or a timeline is read THE SYSTEM SHALL use a fixed number of queries, whatever the
   number of changes and row changes.
4. WHEN routes or schemas change THE SYSTEM SHALL have `packages/api-client` regenerated.
5. WHEN the test suites run THE SYSTEM SHALL keep total coverage at or above 90 % for the API and
   85 % for the web.
6. WHEN the field differences and the cursor are tested THE SYSTEM SHALL check them with
   Hypothesis.

## Out of scope

- Restoring what a record holds one row at a time (a pin, a BOM line, a net) (decision 6).
- Re-creating what was deleted for good (decision 7).
- Backfilling history from before this release (decision 8).
- Filtering the feed by user, kind or date.
- Showing a source file's change as a line-by-line diff: its fields say it changed.
- Pruning history after an age.
