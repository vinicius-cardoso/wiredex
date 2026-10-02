"""What restoring a change does (17-history, decisions 8 and 9).

A restore puts a record's own fields back as they were just before the change: the whole of
them, so the record comes back as that version was, not only the fields the change touched. Only
a part, a unit, a project and a firmware have fields a restore puts back, each through its own
module's edit; a change that moved its record to the trash is undone by the trash instead.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from wiredex.history.domain.errors import NotRestorableError
from wiredex.history.domain.history import Operation, RecordKind, RecordRef, RowChange

# What a restore puts back, by kind: what the record's own edit takes (requirements decision 6).
EDITABLE_FIELDS: Mapping[RecordKind, frozenset[str]] = {
    RecordKind.PART: frozenset(
        {"category_id", "name", "manufacturer", "mpn", "package", "attributes"}
    ),
    RecordKind.UNIT: frozenset({"serial", "mac"}),
    RecordKind.PROJECT: frozenset({"name", "description", "tags"}),
    RecordKind.FIRMWARE: frozenset({"name", "target", "framework", "description"}),
}


@dataclass(frozen=True, slots=True)
class PutBack:
    """The record's editable fields as they were before the change, for its module's edit."""

    record: RecordRef
    fields: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class TakeOutOfTrash:
    """The change moved the record to the trash: restoring it is restoring from the trash."""

    record: RecordRef


type RestorePlan = PutBack | TakeOutOfTrash


def plan_restore(record: RecordRef, own_row: RowChange | None) -> RestorePlan:
    """What restoring the change means, or `NotRestorableError` saying why it can't be.

    `own_row` is the record's own row in the change, with its whole snapshots: a restore puts
    back what the database kept, never a shortened value.
    """
    editable = EDITABLE_FIELDS.get(record.kind)
    if editable is None:
        raise NotRestorableError("only a part, a unit, a project or a firmware can be restored")
    if own_row is None or own_row.operation is not Operation.UPDATE or own_row.before is None:
        raise NotRestorableError("this change didn't edit the record, so there is nothing to undo")
    changed = set(own_row.changed_names())
    if "trashed_at" in changed:
        if own_row.before.get("trashed_at") is None:
            return TakeOutOfTrash(record)
        raise NotRestorableError("this change took the record out of the trash")
    if not changed & editable:
        raise NotRestorableError("this change didn't edit what a restore puts back")
    return PutBack(record, {name: own_row.before.get(name) for name in sorted(editable)})


def restorable(record: RecordRef, own_row: RowChange | None) -> bool:
    """Whether `plan_restore` would plan something, so the page offers it only where it works."""
    try:
        plan_restore(record, own_row)
    except NotRestorableError:
        return False
    return True
