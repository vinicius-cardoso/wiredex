"""What history gives over HTTP, in primitives only: no domain object reaches a field, and the
`from_*` classmethods do the converting, as every module's schemas do.

The wire carries a change's fields as text, never its snapshots (decision 5): what a person reads,
with nothing of the bookkeeping, and nothing long.
"""

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel

from wiredex.history.domain.history import (
    Action,
    Change,
    FieldChange,
    HistoryPage,
    Operation,
    RecordKind,
    RecordRef,
    RowChange,
    RowKind,
)
from wiredex.history.domain.restore import restorable

# The domain's enums spelled out for the wire, so the generated client gets unions it can switch
# on. A test keeps each in step with its enum, as the other modules do.
type RecordKindName = Literal["part", "unit", "project", "firmware", "category", "location"]
type TimelineKindName = Literal["part", "unit", "project", "firmware"]
type RowKindName = Literal[
    "part",
    "pin",
    "attachment",
    "category",
    "attribute",
    "location",
    "unit",
    "flash",
    "project",
    "revision",
    "bom_line",
    "designator",
    "net",
    "net_pin",
    "firmware",
    "version",
    "runs_on",
    "source_file",
]
type OperationName = Literal["insert", "update", "delete"]
type ActionName = Literal[
    "created", "edited", "moved_to_trash", "restored_from_trash", "restored_version", "deleted"
]


class FieldChangeResponse(BaseModel):
    """One field of a row, as text before and after; an insert has no before, a delete no
    after (requirement 2.2)."""

    name: str
    before: str | None
    after: str | None

    @classmethod
    def from_field(cls, field: FieldChange) -> Self:
        return cls(name=field.name, before=field.before, after=field.after)


class RowChangeResponse(BaseModel):
    """One row a change inserted, updated or deleted, named by its snapshot."""

    kind: RowKindName
    operation: OperationName
    label: str | None
    fields: list[FieldChangeResponse]

    @classmethod
    def from_row(cls, row: RowChange) -> Self:
        return cls(
            kind=_row_kind(row.kind),
            operation=_operation(row.operation),
            label=row.label,
            fields=[FieldChangeResponse.from_field(field) for field in row.fields()],
        )


class RecordResponse(BaseModel):
    """The record a change is about, named as it was then (requirement 1.7)."""

    kind: RecordKindName
    id: UUID
    label: str | None

    @classmethod
    def from_record(cls, record: RecordRef) -> Self:
        return cls(kind=_record_kind(record.kind), id=record.id, label=record.label)


class ChangeResponse(BaseModel):
    """One change: when, who (None for Wiredex itself), why, which record and what happened to
    it, its first rows and how many more, and whether restoring it puts the record back."""

    id: int
    occurred_at: datetime
    actor: str | None
    reason: str | None
    record: RecordResponse
    action: ActionName
    rows: list[RowChangeResponse]
    more_rows: int
    restorable: bool

    @classmethod
    def from_change(cls, change: Change) -> Self:
        return cls(
            id=change.id,
            occurred_at=change.occurred_at,
            actor=change.actor_name,
            reason=change.reason,
            record=RecordResponse.from_record(change.record),
            action=_action(change.action),
            rows=[RowChangeResponse.from_row(row) for row in change.rows],
            more_rows=change.more_rows,
            restorable=restorable(change.record, change.own_row),
        )


class HistoryPageResponse(BaseModel):
    """A page of changes, newest first, and the cursor reading the next, or None at the end."""

    changes: list[ChangeResponse]
    next_cursor: str | None

    @classmethod
    def from_page(cls, page: HistoryPage) -> Self:
        return cls(
            changes=[ChangeResponse.from_change(change) for change in page.changes],
            next_cursor=None if page.next is None else page.next.encode(),
        )


# mypy reads an enum's value as the literals its members hold, so a new member stops
# type-checking here until the wire contract above lists it too.
def _record_kind(kind: RecordKind) -> RecordKindName:
    name: RecordKindName = kind.value
    return name


def _row_kind(kind: RowKind) -> RowKindName:
    name: RowKindName = kind.value
    return name


def _operation(operation: Operation) -> OperationName:
    name: OperationName = operation.value
    return name


def _action(action: Action) -> ActionName:
    name: ActionName = action.value
    return name
