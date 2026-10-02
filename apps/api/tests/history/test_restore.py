"""What restoring a change does (17-history, decisions 8 and 9)."""

from uuid import uuid4

import pytest

from wiredex.history.domain.errors import NotRestorableError
from wiredex.history.domain.history import Operation, RecordKind, RecordRef, RowChange, RowKind
from wiredex.history.domain.restore import (
    EDITABLE_FIELDS,
    PutBack,
    TakeOutOfTrash,
    plan_restore,
    restorable,
)

PART = RecordRef(RecordKind.PART, uuid4(), "R 4k7")
MOVED = "2026-10-01T09:00:00+00:00"

BEFORE = {
    "id": str(PART.id),
    "category_id": str(uuid4()),
    "name": "R 4k7",
    "manufacturer": "Yageo",
    "mpn": "RC0805FR-074K7",
    "package": "0805",
    "attributes": {"resistance": 4700},
    "trashed_at": None,
}


def an_update(changes: dict[str, object]) -> RowChange:
    after = {**BEFORE, **changes}
    return RowChange(RowKind.PART, Operation.UPDATE, True, tuple(sorted(changes)), BEFORE, after)


def test_an_edit_puts_back_every_editable_field_as_it_was() -> None:
    plan = plan_restore(PART, an_update({"mpn": "RC0805FR-074K7L"}))

    assert isinstance(plan, PutBack)
    assert plan.record == PART
    # The whole version, not only the field the change touched.
    assert set(plan.fields) == EDITABLE_FIELDS[RecordKind.PART]
    assert plan.fields["mpn"] == "RC0805FR-074K7"
    assert plan.fields["attributes"] == {"resistance": 4700}


def test_a_move_to_the_trash_is_undone_by_the_trash() -> None:
    assert plan_restore(PART, an_update({"trashed_at": MOVED})) == TakeOutOfTrash(PART)


@pytest.mark.parametrize(
    ("record", "row", "why"),
    [
        (
            RecordRef(RecordKind.CATEGORY, uuid4(), "Resistors"),
            RowChange(RowKind.CATEGORY, Operation.UPDATE, True, ("name",), {"name": "A"}, {}),
            "only a part",
        ),
        (PART, None, "didn't edit the record"),
        (
            PART,
            RowChange(RowKind.PART, Operation.INSERT, True, None, None, BEFORE),
            "didn't edit the record",
        ),
        (
            PART,
            RowChange(RowKind.PART, Operation.DELETE, True, None, BEFORE, None),
            "didn't edit the record",
        ),
    ],
)
def test_what_cant_be_restored_says_why(record: RecordRef, row: RowChange | None, why: str) -> None:
    with pytest.raises(NotRestorableError, match=why):
        plan_restore(record, row)
    assert not restorable(record, row)


def test_taking_a_record_out_of_the_trash_isnt_undone() -> None:
    back = RowChange(
        RowKind.PART,
        Operation.UPDATE,
        True,
        ("trashed_at",),
        {**BEFORE, "trashed_at": MOVED},
        BEFORE,
    )
    with pytest.raises(NotRestorableError, match="out of the trash"):
        plan_restore(PART, back)


def test_a_change_to_nothing_a_restore_puts_back_isnt_restorable() -> None:
    unit = RecordRef(RecordKind.UNIT, uuid4(), "WX-U-0007")
    moved = RowChange(
        RowKind.UNIT,
        Operation.UPDATE,
        True,
        ("lot_id", "status"),
        {"serial": "SN-1", "mac": None, "status": "in_stock", "lot_id": str(uuid4())},
        {"serial": "SN-1", "mac": None, "status": "retired", "lot_id": str(uuid4())},
    )
    with pytest.raises(NotRestorableError, match="didn't edit what a restore puts back"):
        plan_restore(unit, moved)


@pytest.mark.parametrize(
    ("kind", "row_kind", "field"),
    [
        (RecordKind.UNIT, RowKind.UNIT, "serial"),
        (RecordKind.PROJECT, RowKind.PROJECT, "tags"),
        (RecordKind.FIRMWARE, RowKind.FIRMWARE, "target"),
    ],
)
def test_each_kind_puts_back_its_own_fields(
    kind: RecordKind, row_kind: RowKind, field: str
) -> None:
    record = RecordRef(kind, uuid4(), "x")
    before = {name: f"old {name}" for name in EDITABLE_FIELDS[kind]}
    after = {**before, field: "new"}
    row = RowChange(row_kind, Operation.UPDATE, True, (field,), before, after)

    plan = plan_restore(record, row)

    assert isinstance(plan, PutBack)
    assert plan.fields == before
    assert restorable(record, row)
