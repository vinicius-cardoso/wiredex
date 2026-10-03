"""A change as history reads it back: the rows one transaction wrote to one record, each as the
fields it changed, before and after (17-history, decisions 3, 5 and 6).

The database records the snapshots; this file is what turns them into what a person reads. A
row's own columns are the fields, minus the bookkeeping every row has and the column naming the
record it belongs to. A value is shown as text, shortened past 300 characters, so a source file's
text never fills a page.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from wiredex.history.domain.errors import InvalidHistoryCursorError, InvalidHistoryFilterError
from wiredex.history.domain.values import ChangeId

# How many of a change's rows a page shows, the record's own row first (requirement 2.3).
MAX_ROWS_SHOWN = 20

# How many changes one read answers: 50 unless asked, never more than 100 (requirement 2.4).
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100

# Past this many characters a value is cut, and an ellipsis says so (requirement 2.2).
SHORTENED_AT = 300
_ELLIPSIS = "…"

# What a transaction names when it puts a record back as it was (decision 8).
RESTORE_REASON = "restore"

# A cursor is a change id, a positive bigint: at most 19 digits.
MAX_CURSOR_LENGTH = 19
_MAX_BIGINT = 2**63 - 1

# A fragment of a record's name to narrow the activity by: as long as the box it is typed in.
MAX_FILTER_TEXT_LENGTH = 80

type Snapshot = Mapping[str, object]


class RecordKind(StrEnum):
    """What a change is about: a record with a page or a tree of its own (decision 2)."""

    PART = "part"
    UNIT = "unit"
    PROJECT = "project"
    FIRMWARE = "firmware"
    CATEGORY = "category"
    LOCATION = "location"


class RowKind(StrEnum):
    """What a tracked row is, one kind per tracked table."""

    PART = "part"
    PIN = "pin"
    ATTACHMENT = "attachment"
    CATEGORY = "category"
    ATTRIBUTE = "attribute"
    LOCATION = "location"
    UNIT = "unit"
    FLASH = "flash"
    PROJECT = "project"
    REVISION = "revision"
    BOM_LINE = "bom_line"
    DESIGNATOR = "designator"
    NET = "net"
    NET_PIN = "net_pin"
    FIRMWARE = "firmware"
    VERSION = "version"
    RUNS_ON = "runs_on"
    SOURCE_FILE = "source_file"


class Operation(StrEnum):
    INSERT = "insert"
    UPDATE = "update"
    DELETE = "delete"


class Action(StrEnum):
    """What a change did to its record, read off the record's own row (decision 6)."""

    CREATED = "created"
    EDITED = "edited"
    MOVED_TO_TRASH = "moved_to_trash"
    RESTORED_FROM_TRASH = "restored_from_trash"
    RESTORED_VERSION = "restored_version"
    DELETED = "deleted"


# Every row has these, and none of them says what changed.
_BOOKKEEPING = frozenset({"id", "workspace_id", "created_at", "updated_at"})

# The column naming the record or the parent a row belongs to: the change already says which.
_LINKS: Mapping[RowKind, frozenset[str]] = {
    RowKind.PIN: frozenset({"part_id"}),
    RowKind.ATTACHMENT: frozenset({"subject_kind", "subject_id"}),
    RowKind.ATTRIBUTE: frozenset({"category_id"}),
    RowKind.FLASH: frozenset({"unit_id"}),
    RowKind.REVISION: frozenset({"project_id"}),
    RowKind.BOM_LINE: frozenset({"revision_id"}),
    RowKind.DESIGNATOR: frozenset({"revision_id"}),
    RowKind.NET: frozenset({"revision_id"}),
    RowKind.NET_PIN: frozenset({"revision_id"}),
    RowKind.VERSION: frozenset({"firmware_id"}),
    RowKind.RUNS_ON: frozenset({"firmware_id"}),
    RowKind.SOURCE_FILE: frozenset({"version_id"}),
}

# The field that names a row, by kind; a pin and a net pin are named by two.
_NAMES: Mapping[RowKind, str] = {
    RowKind.PART: "name",
    RowKind.ATTACHMENT: "title",
    RowKind.CATEGORY: "name",
    RowKind.ATTRIBUTE: "label",
    RowKind.LOCATION: "name",
    RowKind.UNIT: "code",
    RowKind.FLASH: "unit_code",
    RowKind.PROJECT: "name",
    RowKind.REVISION: "label",
    RowKind.DESIGNATOR: "designator",
    RowKind.NET: "name",
    RowKind.FIRMWARE: "name",
    RowKind.VERSION: "version",
    RowKind.SOURCE_FILE: "path",
}


def shorten(text: str) -> str:
    """The text, or its first 300 characters and an ellipsis (property 3). Shortening twice
    changes nothing, so a value the database already shortened reads the same."""
    if len(text) <= SHORTENED_AT:
        return text
    return text[:SHORTENED_AT] + _ELLIPSIS


def shown(value: object) -> str | None:
    """A stored value as text: JSON's own spelling for a switch, a list or an object, the
    number as it was written, and nothing for a null."""
    if value is None:
        return None
    if isinstance(value, str):
        return shorten(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | Decimal | float):
        return str(value)
    return shorten(json.dumps(value, ensure_ascii=False, separators=(", ", ": "), default=str))


@dataclass(frozen=True, slots=True)
class FieldChange:
    """One field of a row, as it was and as it became; an insert has no before, a delete no
    after."""

    name: str
    before: str | None
    after: str | None


@dataclass(frozen=True, slots=True)
class RowChange:
    """One tracked row a change inserted, updated or deleted, with its snapshots.

    `changed` is what the trigger listed for an update, compared on the whole values: the
    snapshots may arrive shortened, and two long texts differing past their first 300
    characters would read alike.
    """

    kind: RowKind
    operation: Operation
    own: bool  # the record's own row, not one of what it holds
    changed: tuple[str, ...] | None
    before: Snapshot | None
    after: Snapshot | None

    @property
    def label(self) -> str | None:
        """What names the row, from its last snapshot: a part's name, a pin's number and label,
        a net pin's designator and pin, a file's path. A BOM line and a runs-on link have none."""
        snapshot = self.after if self.after is not None else self.before
        if snapshot is None:
            return None
        if self.kind is RowKind.PIN:
            return _joined(snapshot, "number", "label", " ")
        if self.kind is RowKind.NET_PIN:
            return _joined(snapshot, "designator", "pin", ".")
        name = _NAMES.get(self.kind)
        return None if name is None else _text(snapshot.get(name))

    def fields(self) -> tuple[FieldChange, ...]:
        """The visible fields that changed, by name (property 1): an update's changed fields,
        an insert's every field, a delete's every field."""
        hidden = _BOOKKEEPING | _LINKS.get(self.kind, frozenset())
        before, after = self.before or {}, self.after or {}
        names = sorted(name for name in self.changed_names() if name not in hidden)
        return tuple(
            FieldChange(
                name,
                None if self.operation is Operation.INSERT else shown(before.get(name)),
                None if self.operation is Operation.DELETE else shown(after.get(name)),
            )
            for name in names
        )

    def changed_names(self) -> tuple[str, ...]:
        """The fields the row changed, bookkeeping included: an update's as the trigger listed
        them, or as the snapshots differ when it listed none; every field of an insert or a
        delete."""
        before, after = self.before or {}, self.after or {}
        if self.operation is Operation.INSERT:
            return tuple(after)
        if self.operation is Operation.DELETE:
            return tuple(before)
        if self.changed is not None:
            return self.changed
        names = set(before) | set(after)
        return tuple(name for name in names if before.get(name) != after.get(name))


@dataclass(frozen=True, slots=True)
class RecordRef:
    """The record a change is about, named as it was when the change was made (1.7)."""

    kind: RecordKind
    id: UUID
    label: str | None


@dataclass(frozen=True, slots=True)
class Change:
    """What one transaction wrote to one record: when, who, why, and its rows, at most 20 of
    them, the record's own row first; `row_count` is how many it wrote in all."""

    id: ChangeId
    occurred_at: datetime
    actor_name: str | None  # None: Wiredex itself, a job or the command line
    reason: str | None
    record: RecordRef
    rows: tuple[RowChange, ...]
    row_count: int

    @property
    def own_row(self) -> RowChange | None:
        return next((row for row in self.rows if row.own), None)

    @property
    def more_rows(self) -> int:
        return max(self.row_count - len(self.rows), 0)

    @property
    def action(self) -> Action:
        """Created, deleted, moved to the trash or back, restored, or edited (decision 6)."""
        own = self.own_row
        if own is not None and own.operation is Operation.INSERT:
            return Action.CREATED
        if own is not None and own.operation is Operation.DELETE:
            return Action.DELETED
        if own is not None and "trashed_at" in own.changed_names():
            trashed = (own.after or {}).get("trashed_at") is not None
            return Action.MOVED_TO_TRASH if trashed else Action.RESTORED_FROM_TRASH
        if self.reason == RESTORE_REASON:
            return Action.RESTORED_VERSION
        return Action.EDITED


@dataclass(frozen=True, slots=True)
class ActivityFilter:
    """What narrows the activity: the kind of record, what the change did to it, a fragment of
    the record's name as the change left it, or any of them together.

    The text is trimmed and its whitespace collapsed, and matches ignoring case; a blank one
    narrows nothing. `matches` is the rule the repository's query follows, so the in-memory
    fake and the SQL select the same changes.
    """

    kind: RecordKind | None = None
    action: Action | None = None
    text: str | None = None

    def __post_init__(self) -> None:
        if self.text is None:
            return
        collapsed = " ".join(self.text.split())
        if len(collapsed) > MAX_FILTER_TEXT_LENGTH:
            raise InvalidHistoryFilterError(
                f"the text to search the activity by is at most {MAX_FILTER_TEXT_LENGTH} characters"
            )
        object.__setattr__(self, "text", collapsed or None)

    def matches(self, change: Change) -> bool:
        if self.kind is not None and change.record.kind is not self.kind:
            return False
        if self.action is not None and change.action is not self.action:
            return False
        if self.text is None:
            return True
        # Lower-cased, as the query's ILIKE compares, rather than case-folded.
        label = change.record.label
        return label is not None and self.text.lower() in label.lower()


@dataclass(frozen=True, slots=True)
class ChangeCursor:
    """Where the last page stopped: the last change's id, as text."""

    change_id: ChangeId

    def encode(self) -> str:
        return str(self.change_id)

    @classmethod
    def decode(cls, text: str) -> ChangeCursor:
        """The cursor the text carries; anything else is the one refusal (requirement 2.5)."""
        if not (0 < len(text) <= MAX_CURSOR_LENGTH) or not text.isascii() or not text.isdigit():
            raise InvalidHistoryCursorError("this cursor can't be read")
        value = int(text)
        if not 0 < value <= _MAX_BIGINT:
            raise InvalidHistoryCursorError("this cursor can't be read")
        return cls(ChangeId(value))


@dataclass(frozen=True, slots=True)
class HistoryPage:
    """A page of changes, newest first, and the cursor reading the next, or None at the end."""

    changes: tuple[Change, ...]
    next: ChangeCursor | None

    @classmethod
    def of(cls, found: Sequence[Change], limit: int) -> HistoryPage:
        """The first `limit` of `found`, which holds up to one more: that one says a next page
        exists, and the last change kept is where it starts."""
        kept = tuple(found[:limit])
        if len(found) <= limit or not kept:
            return cls(kept, None)
        return cls(kept, ChangeCursor(kept[-1].id))


def _text(value: object) -> str | None:
    return None if value is None else str(value)


def _joined(snapshot: Snapshot, first: str, second: str, separator: str) -> str | None:
    parts = [str(value) for value in (snapshot.get(first), snapshot.get(second)) if value]
    return separator.join(parts) or None
