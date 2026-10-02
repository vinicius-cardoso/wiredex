# Design Document: history

## Overview

The second of four specs in `v0.8.0` Everyday use. It delivers the roadmap line *History for
everything*: every change kept with who, when and before/after, a timeline on each record's
page, a workspace activity feed, and restoring a past version as a new change.

The database does the recording. One trigger function, `record_history()`, runs after every
insert, update and delete on the tracked tables, and writes a row change grouped into a change
per transaction and record, in the writer's own transaction. Each transaction names its user and
an optional reason next to the workspace it already names, so the trigger knows who and why. A
new `history` module reads the changes for the feed and the timelines, and restores a past version
through the module that owns the record, in that module's own transaction.

Three things carry the design: how a write becomes a change without any module knowing (decisions
1 to 4), what a change says when it is read (decisions 5 to 7), and how a restore goes through the
owner's rules (decisions 8 and 9).

**Owner decisions that bind this spec**, and what each does here:

- **One PR per spec with auto-merge; the release PR waits for 19-command-palette, and only the
  owner merges it** (2026-09-27). No task here carries a `Release-As` footer.
- **ADR 0001**: modules never import each other. `history` reads only its own tables; bootstrap
  hands it whether a record exists and how to restore one.
- **ADR 0002**: the ledger is append-only, and the database refuses an edit. History is too.
- **ADR 0007**: every workspace table is filtered twice. Both new tables call
  `isolate_by_workspace`.

**Decisions this spec makes (2026-10-01), for the owner to check.** They are listed with their
reasons in [requirements.md](requirements.md)'s introduction; here is how each is built.

1. **`record_history()`, one trigger function, attached to each tracked table by
   `track_history(op.execute, table)`.** The helper lives in
   `shared_kernel/infrastructure/history_tracking.py` beside `isolate_by_workspace`, and creates
   `AFTER INSERT OR UPDATE OR DELETE ... FOR EACH ROW EXECUTE FUNCTION record_history()`. The
   function is `SECURITY DEFINER` with a fixed `search_path`, so it writes history as the schema
   owner whatever role wrote the row, which is what lets the API's role lose `INSERT` and `UPDATE`
   on history (decision 10 of requirements).

2. **The record a row belongs to is found by `history_root(table, row)`.** A SQL function with one
   branch per tracked table answers the record's kind, id and name: a part row is its own record;
   a pin's is its part; a revision's, BOM line's, designator's, net's and net pin's is the
   revision's project; a version's, source file's and runs-on link's is the firmware; a flash's is
   its unit, named by the code the flash keeps; an attachment's follows its subject, a revision's
   to its project. When the parent row is already gone, which happens only while a record is
   deleted with its contents, the row change is not recorded: the record's own deletion is
   (requirement 1.5). A table tracked later replaces the function in its migration.

3. **A change is `(transaction, record)`, upserted by the trigger.** `history_changes` holds one row
   per transaction id (`pg_current_xact_id()`) and record, with when, who, why and the record's
   name as the transaction left it; `history_entries` holds the row changes, each with its
   snapshots (`to_jsonb(OLD)`, `to_jsonb(NEW)`) and the names of the fields that changed, computed
   in the trigger. An update whose only change is `updated_at` is skipped, as is one that changes
   nothing (requirement 1.3).

4. **Who and why ride the transaction's settings.** `SqlUnitOfWork.__aenter__` already names the
   workspace with one `set_config`; it now names `app.user_id`, `app.user_name` and
   `app.change_reason` in the same statement, read from `shared_kernel/infrastructure/change_context.py`:
   a `ContextVar` holding the request's `Actor(id, name)` and another holding a reason. The
   composition root sets the actor in each router's workspace closure, right after
   `authenticated_user`, so every module's writes carry it without a parameter; the command line
   sets none, and its changes read as Wiredex's.

5. **The read side answers diffs, not snapshots.** `history_trim(jsonb)` shortens every value
   longer than 300 characters as the rows are read, so a page never carries a source file's text;
   the domain turns each row change into its kind, operation, label and changed fields, leaving out
   `id`, `workspace_id`, `created_at`, `updated_at` and the column naming its record (a pin's
   `part_id`). A change lists at most 20 row changes, its record's own row first, and how many
   more (requirement 2.3).

6. **What happened is read off the record's own row.** Its insert is *created*, its delete
   *deleted*, an update setting `trashed_at` *moved to the trash* and one clearing it *restored
   from the trash*, a change with the reason `restore` *restored to an earlier version*, and
   anything else *edited*.

7. **Pages by change id.** Change ids are a `bigint` identity: a page is the changes below a cursor,
   newest first, over `(workspace_id, id DESC)` for the feed and `(workspace_id, root_kind,
   root_id, id DESC)` for a timeline, and their row changes in one more query, ranked per change.
   The cursor is the last change's id as text, digits only, at most 19.

8. **A restore puts back the `before` of the record's own row, through the module.**
   `RestoreVersion` reads the change in a history transaction and closes it, then hands the
   snapshot to the `VersionRestorers` port. Bootstrap's restorers call `UpdatePart`,
   `RelabelUnit`, `UpdateProject` or `UpdateFirmware` under the reason `restore`, so the module
   refuses what it would refuse from its form and the trigger records the restore as a new change.
   A change that moved its record to the trash goes to the trash's `RestoreFromTrash` instead.

9. **A change is restorable when its record is a part, unit, project or firmware and its own row
   was updated in a field a restore puts back, or moved to the trash.** The domain says so, and
   the API answers it with each change, so the web offers the button only where it works.

10. **A demo bench's history goes with its seed.** `ClearHistory` deletes a workspace's changes
    (their row changes cascade), and `_restore_benches` runs it after each bench's samples are
    back, for an invite and for the nightly reset alike.

11. **The web: an *Activity* page and a *History* section.** `/activity` lists the feed; each of
    the four record pages gets a *History* region with a *Show history* button that loads its
    timeline on demand. Both render the same `ChangeList`; a restorable change offers *Restore the
    version before this change*, which asks in place.

**Seen while designing, not changed here:**

- Pinouts, BOM designators and net pins are saved by replacing their rows, so a one-pin edit reads
  as every pin removed and added again. The change says so row by row, capped at 20.
- `UpdatePart` and the other edits read the record without locking it, so a restore racing an
  edit is decided by the last to commit, as two edits are today.
- References to other records (a BOM line's part, a unit's lot) show as ids, not names.

**In scope:** migration `0023` with the two tables, the three functions and the triggers; the
transaction's user and reason; the `history` module; the routes; the restorers; the demo benches'
clearing; the *Activity* page and the four *History* sections; the E2E journey.

**Out of scope:** restoring rows one at a time, re-creating deleted records, backfilling, filters
on the feed, a line diff of source files, pruning by age.

## Architecture

```mermaid
flowchart LR
    subgraph modules["catalog · inventory · projects · firmware · files"]
        UOW["SqlUnitOfWork: names workspace,<br/>user and reason"]
    end
    subgraph db[(Postgres)]
        TRIG["record_history() on 18 tables"]
        HC["history_changes"]
        HE["history_entries"]
    end
    subgraph history
        HAPI["api: /api/history"]
        HUC["application: ListActivity, ListTimeline,<br/>RestoreVersion, ClearHistory"]
        HDOM["domain: Change, RowChange,<br/>FieldChange, ChangeCursor"]
    end
    subgraph bootstrap
        ACT["app.py: act_as(user) in every<br/>workspace closure"]
        ROOTS["history.py: RecordDirectory,<br/>Restorers"]
    end
    ACT --> UOW
    UOW -->|writes| TRIG --> HC & HE
    HAPI --> HUC --> HDOM
    HUC -->|reads| HC & HE
    HUC -->|Records, VersionRestorers| ROOTS --> modules
```

## Components and Interfaces

### Migration `0023_history.py`

```sql
CREATE TABLE history_changes (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    workspace_id uuid NOT NULL,
    transaction_id bigint NOT NULL,
    occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    actor_id uuid, actor_name text, reason text,
    root_kind text NOT NULL, root_id uuid NOT NULL, root_label text,
    entry_count integer NOT NULL DEFAULT 1,
    CONSTRAINT uq_history_changes_transaction UNIQUE (workspace_id, transaction_id, root_kind, root_id)
);
CREATE INDEX ix_history_changes_feed ON history_changes (workspace_id, id DESC);
CREATE INDEX ix_history_changes_timeline ON history_changes (workspace_id, root_kind, root_id, id DESC);

CREATE TABLE history_entries (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    change_id bigint NOT NULL REFERENCES history_changes (id) ON DELETE CASCADE,
    workspace_id uuid NOT NULL,
    table_name text NOT NULL, operation text NOT NULL, own boolean NOT NULL,
    record_id uuid, changed text[], before jsonb, after jsonb
);
CREATE INDEX ix_history_entries_change_id ON history_entries (change_id, id);
```

Both call `isolate_by_workspace`, and `REVOKE INSERT, UPDATE ON history_changes, history_entries
FROM wiredex_app` takes away what the default privileges of `0004` granted. `history_root(text,
jsonb)`, `history_trim(jsonb)` and `record_history()` follow, then `track_history` on:

| Table | Row kind | Record |
| --- | --- | --- |
| `part_definitions` | part | itself |
| `pins` | pin | its part |
| `attachments` | attachment | its subject; a revision's project |
| `categories` | category | itself |
| `attribute_definitions` | attribute | its category |
| `locations` | location | itself |
| `units` | unit | itself |
| `flashes` | flash | its unit, named by `unit_code` |
| `projects` | project | itself |
| `revisions` | revision | its project |
| `bom_lines`, `bom_designators`, `nets`, `net_pins` | BOM line, designator, net, net pin | the revision's project |
| `firmware` | firmware | itself |
| `firmware_versions`, `firmware_revisions` | version, runs on | its firmware |
| `source_files` | source file | the version's firmware |

`downgrade` drops the triggers, the functions and the tables.

### Shared kernel

```python
# shared_kernel/infrastructure/change_context.py
@dataclass(frozen=True, slots=True)
class Actor:
    id: UUID
    name: str


def act_as(actor: Actor) -> None: ...  # the request's task, from bootstrap
def acting() -> Actor | None: ...
@contextmanager
def changing_for(reason: str) -> Iterator[None]: ...
def reason() -> str | None: ...


# shared_kernel/infrastructure/row_security.py
async def name_the_transaction(
    session: AsyncSession, workspace_id: UUID, actor: Actor | None, reason: str | None
) -> None:
    """`app.workspace_id`, `app.user_id`, `app.user_name` and `app.change_reason`, local to the
    transaction, in one statement."""


# shared_kernel/infrastructure/history_tracking.py
TRACKED_TABLES: tuple[str, ...]


def track_history(execute: Execute, table: str) -> None: ...
def stop_tracking(execute: Execute, table: str) -> None: ...
```

`SqlUnitOfWork.__aenter__` calls `name_the_transaction` instead of `scope_to_workspace`, still one
statement, so every count the integration tests hold stays as it is.

### The history module

```text
wiredex/history/
├── domain/history.py       RecordKind, RowKind, Operation, Action, FieldChange, RowChange,
│                           Change, ChangeCursor, HistoryPage
├── domain/restore.py       EDITABLE_FIELDS, restorable(), RestorePlan
├── domain/errors.py        HistoryError, ChangeNotFoundError, RecordNotFoundError,
│                           InvalidHistoryCursorError, NotRestorableError
├── domain/values.py        WorkspaceId, ChangeId
├── application/ports.py    HistoryChanges, HistoryUnitOfWork, Records, VersionRestorers
├── application/history.py  ListActivity, ListTimeline, RestoreVersion, ClearHistory
├── infrastructure/         orm.py, repositories.py (SqlHistoryChanges), unit_of_work.py
└── api/                    router.py, schemas.py
```

```python
class RecordKind(StrEnum):
    PART = "part"
    UNIT = "unit"
    PROJECT = "project"
    FIRMWARE = "firmware"
    CATEGORY = "category"
    LOCATION = "location"


@dataclass(frozen=True, slots=True)
class FieldChange:
    name: str
    before: str | None
    after: str | None


@dataclass(frozen=True, slots=True)
class RowChange:
    kind: RowKind
    operation: Operation
    own: bool  # the record's own row
    # An update's changed fields, as the trigger listed them.
    changed: tuple[str, ...] | None
    before: Mapping[str, object] | None
    after: Mapping[str, object] | None

    @property
    def label(self) -> str | None: ...  # name, number, code, path... by kind
    def fields(self) -> tuple[FieldChange, ...]: ...


@dataclass(frozen=True, slots=True)
class Change:
    id: ChangeId
    occurred_at: datetime
    actor_name: str | None
    reason: str | None
    record: RecordRef  # kind, id, label
    rows: tuple[RowChange, ...]  # at most 20, its own row first
    row_count: int

    @property
    def action(self) -> Action: ...
```

| Port | Implemented by | What |
| --- | --- | --- |
| `HistoryChanges` | `SqlHistoryChanges` | `page(before, limit, record)`, `own_row(change_id)`, `clear()` |
| `Records` | bootstrap's `RecordDirectory` | whether a part, unit, project or firmware is live in the workspace, through `GetPart`, `GetUnit`, `GetProject`, `GetFirmware` |
| `VersionRestorers` | bootstrap's `Restorers` | `put_back(kind, id, before)` and `restore_from_trash(kind, id)` |

| Use case | What it does |
| --- | --- |
| `ListActivity` | a page of the feed |
| `ListTimeline` | asks `Records` first, a 404 for a record that isn't live, then a page of its changes |
| `RestoreVersion` | reads the change's own row in a history transaction, closes it, plans the restore, then hands it to `VersionRestorers` |
| `ClearHistory` | deletes a workspace's changes |

### Bootstrap

- `bootstrap/app.py`: each `_…_workspace` closure calls `act_as(Actor(current.user.id,
  current.user.name.value))` after `authenticated_user`; the history router is mounted with a
  `_history_workspace` closure.
- `bootstrap/history.py`: `RecordDirectory`, `Restorers` (each module's edit under
  `changing_for("restore")`, refusals turned into `NotRestorableError` with the module's sentence,
  a missing record into `RecordNotFoundError`), `history_use_cases`, `clear_history_use_case`.
- `bootstrap/cli.py`: `_restore_benches` clears each bench's history once its samples are back.

### HTTP

| Method and path | Answers | Requirement |
| --- | --- | --- |
| `GET /api/history?limit=&cursor=` | `HistoryPageResponse` | 2 |
| `GET /api/history/{kind}/{record_id}?limit=&cursor=` | `HistoryPageResponse`, 404 | 3 |
| `POST /api/history/changes/{change_id}/restore` | 204, 404, 409 | 4 |

```python
class FieldChangeResponse(BaseModel):
    name: str
    before: str | None
    after: str | None


class RowChangeResponse(BaseModel):
    kind: RowKindName
    operation: OperationName  # "insert" | "update" | "delete"
    label: str | None
    fields: list[FieldChangeResponse]


class ChangeResponse(BaseModel):
    id: int
    occurred_at: datetime
    actor: str | None
    reason: str | None
    record: RecordResponse  # kind, id, label
    action: ActionName
    rows: list[RowChangeResponse]
    more_rows: int
    restorable: bool


class HistoryPageResponse(BaseModel):
    changes: list[ChangeResponse]
    next_cursor: str | None
```

`limit` is `Query(ge=1, le=100)`, 50 by default; `cursor` at most 19 characters; `kind` is
`Literal["part", "unit", "project", "firmware"]`.

### Web

| File | What |
| --- | --- |
| `features/history/history.ts` | `historyKeys`, `useActivity`, `useTimeline(kind, id, enabled)`, `useRestoreVersion`; a restore refreshes `historyKeys.all`, `trashKeys.all` and the record's caches through 16's `cachesOf` |
| `features/history/labels.ts` | Each action's, row kind's and field's i18n key, a field outside the list shown by its name |
| `features/history/ChangeList.tsx` | The changes: time, who, what happened to which record, the rows with their fields before → after, *Restore the version before this change* asking in place, *Show more*, and the note that history starts with this release |
| `features/history/ActivityPage.tsx` | `/activity` |
| `features/history/HistorySection.tsx` | The *History* region of a record page, closed until *Show history* |
| `app/router.tsx`, `app/AppLayout.tsx` | The route, and *Activity* before *Trash* |
| `catalog/PartPage.tsx`, `inventory/UnitPage.tsx`, `projects/ProjectPage.tsx`, `firmware/FirmwarePage.tsx` | The *History* section |

Keys under `history.*` and `nav.activity`, in both locales. `src/test/server.ts` gains `aChange`,
`aRowChange`, `respondWithActivity`, `respondWithTimeline` and `acceptRestores`.

## Data Models

The DDL is above. A change as the feed answers it:

```json
{ "id": 4182, "occurred_at": "2026-10-01T18:02:11Z", "actor": "Owner", "reason": null,
  "record": { "kind": "part", "id": "0199…", "label": "4.7 kΩ 1% 0805" },
  "action": "edited",
  "rows": [ { "kind": "part", "operation": "update", "label": "4.7 kΩ 1% 0805",
              "fields": [ { "name": "mpn", "before": "RC0805FR-074K7", "after": "RC0805FR-074K7L" } ] } ],
  "more_rows": 0, "restorable": true }
```

- Purely additive: two new tables, three functions and eighteen triggers. The previous release
  writes through the triggers unchanged, its transactions naming no user, so a rollback of the
  API keeps recording, as Wiredex.
- `downgrade` drops the triggers first, then the functions and the tables.
- ADR 0007's list grows by `history_changes` and `history_entries`.

## Correctness Properties

### Property 1: a row change's fields are exactly what changed

For any two snapshots, `RowChange.fields()` of an update lists every visible field whose value
differs and no other, each with both values; an insert lists every visible field of `after` and a
delete every visible field of `before`.

### Property 2: a cursor reads back

For any change id, `ChangeCursor.decode(cursor.encode())` is the cursor, and any text that isn't
one is refused.

### Property 3: shortened values stay recognisable

For any text, the shortened value is the text when it fits in 300 characters, and otherwise its
first 300 characters followed by an ellipsis.

## Error Handling

| Case | Status | Detail |
| --- | --- | --- |
| A timeline of a record that isn't live in the workspace | 404 | `RecordNotFoundError` |
| A restore of a change that isn't the workspace's | 404 | `ChangeNotFoundError` |
| A restore of a change that can't be restored | 409 | `NotRestorableError` |
| A restore the module refuses, or of a record no longer in the trash | 409 | the module's sentence |
| A restore of a record since deleted for good | 404 | `RecordNotFoundError` |
| A limit out of range, a cursor the API didn't give, an unknown kind | 422 | |
| No session | 401 | |
| A cookie write without the CSRF header | 403 | |
| The API's role inserting or updating history | refused by Postgres | `permission denied` |

## Testing Strategy

| Level | Files | What |
| --- | --- | --- |
| Domain | `tests/history/test_history.py`, `test_restore.py` | Properties 1 to 3; labels and actions per kind; what is restorable |
| Application | `tests/history/test_history_use_cases.py` | Fakes: the pages, a timeline's 404, restore planning and hand-off, clearing |
| Integration | `tests/integration/test_history_recording.py`, `test_history_reads.py`, `test_history_restore.py`, `test_history_actor.py`, `test_migrations.py`, `test_demo_cli.py` | Each tracked table recorded with its record; skipped no-ops and cascades; a rolled-back write leaving nothing; the app role refused writes; pages in fixed statements; another bench unseen; restores through each module recorded as restores; a user's name from a real request; a bench's history empty after a reset; the round trip at `0023` |
| HTTP | `tests/history/test_history_api.py`, `test_history_auth.py` | Shapes, the limit and cursor 422s, 404s and 409s; 401 and 403 |
| Web | beside each component | The feed, a section opening its timeline, fields before → after, restore asking and refusing, the end note, both languages |
| E2E | `e2e/tests/history.spec.ts` | A part edited twice, its history read on its page, the earlier version restored, the feed showing all three |

## Seams for later specs

| Seam | For | What it is |
| --- | --- | --- |
| `ListActivity` | 18-dashboard | Its newest few changes are the dashboard's recent activity |
| `track_history` | later tables | A table joins history with one call and one branch of `history_root` |
| `changing_for` | later jobs | A job names why it writes, and the feed shows it |

## After this spec

Nothing is documented outside the spec yet: 19-command-palette's last task records this spec's
decisions in an ADR and adds `history` to docs/architecture.md's contexts.
