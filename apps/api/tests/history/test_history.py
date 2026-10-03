"""A change's rows read as fields before and after (17-history, design properties 1 to 3)."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st

from wiredex.history.domain.errors import InvalidHistoryCursorError, InvalidHistoryFilterError
from wiredex.history.domain.history import (
    MAX_CURSOR_LENGTH,
    MAX_FILTER_TEXT_LENGTH,
    RESTORE_REASON,
    SHORTENED_AT,
    Action,
    ActivityFilter,
    Change,
    ChangeCursor,
    FieldChange,
    HistoryPage,
    Operation,
    RecordKind,
    RecordRef,
    RowChange,
    RowKind,
    shorten,
    shown,
)
from wiredex.history.domain.values import ChangeId

AT = datetime(2026, 10, 1, 9, tzinfo=UTC)
PART = RecordRef(RecordKind.PART, uuid4(), "4.7 kΩ 1% 0805")


def an_update(
    before: dict[str, object], after: dict[str, object], kind: RowKind = RowKind.PART
) -> RowChange:
    changed = tuple(sorted(name for name in after if before.get(name) != after.get(name)))
    return RowChange(kind, Operation.UPDATE, True, changed, before, after)


def a_change(*rows: RowChange, reason: str | None = None, count: int | None = None) -> Change:
    return Change(
        ChangeId(7), AT, "Owner", reason, PART, rows, len(rows) if count is None else count
    )


# --- Fields (property 1) ---------------------------------------------------------------------

values = st.one_of(
    st.none(), st.booleans(), st.integers(), st.text(max_size=20), st.lists(st.integers())
)
snapshots = st.dictionaries(st.sampled_from(["name", "mpn", "package", "notes", "id"]), values)


@given(snapshots, snapshots)
def test_an_updates_fields_are_exactly_the_visible_ones_that_differ(
    before: dict[str, object], after: dict[str, object]
) -> None:
    row = an_update(before, after)
    differing = {
        name for name in set(before) | set(after) if before.get(name) != after.get(name)
    } - {"id"}
    listed = {field.name for field in row.fields()}
    # Only the names the trigger listed from `after` count: a key gone from `after` is a
    # column the row no longer has, which the database never does to a row.
    assert listed == {name for name in differing if name in after}
    for field in row.fields():
        assert field.before == shown(before.get(field.name))
        assert field.after == shown(after.get(field.name))


@given(snapshots)
def test_an_insert_lists_every_visible_field_with_no_before(after: dict[str, object]) -> None:
    row = RowChange(RowKind.PART, Operation.INSERT, True, None, None, after)
    assert {field.name for field in row.fields()} == set(after) - {"id"}
    assert all(field.before is None for field in row.fields())


@given(snapshots)
def test_a_delete_lists_every_visible_field_with_no_after(before: dict[str, object]) -> None:
    row = RowChange(RowKind.PART, Operation.DELETE, True, None, before, None)
    assert {field.name for field in row.fields()} == set(before) - {"id"}
    assert all(field.after is None for field in row.fields())


def test_bookkeeping_and_the_link_to_the_record_are_left_out() -> None:
    row = RowChange(
        RowKind.PIN,
        Operation.INSERT,
        False,
        None,
        None,
        {
            "workspace_id": str(uuid4()),
            "part_id": str(uuid4()),
            "number": "3",
            "label": "SDA",
            "created_at": "2026-10-01T09:00:00+00:00",
            "updated_at": "2026-10-01T09:00:00+00:00",
        },
    )
    assert [field.name for field in row.fields()] == ["label", "number"]


def test_an_update_trusts_the_triggers_list_over_shortened_snapshots() -> None:
    # Two long texts differing past their first 300 characters arrive alike.
    cut = shorten("x" * 400)
    row = RowChange(
        RowKind.SOURCE_FILE,
        Operation.UPDATE,
        False,
        ("content",),
        {"content": cut},
        {"content": cut},
    )
    assert row.fields() == (FieldChange("content", cut, cut),)


def test_an_update_with_no_list_compares_its_snapshots() -> None:
    row = RowChange(RowKind.NET, Operation.UPDATE, False, None, {"name": "SDA"}, {"name": "SDI"})
    assert row.fields() == (FieldChange("name", "SDA", "SDI"),)


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (None, None),
        (True, "true"),
        (False, "false"),
        (4700, "4700"),
        (Decimal("0.1"), "0.1"),
        ("RC0805", "RC0805"),
        (["esp32", "i2c"], '["esp32", "i2c"]'),
        ({"resistance": 4700}, '{"resistance": 4700}'),
    ],
)
def test_values_read_as_text(value: object, text: str | None) -> None:
    assert shown(value) == text


# --- Shortening (property 3) -------------------------------------------------------------------


@given(st.text(max_size=SHORTENED_AT * 2))
def test_a_long_value_is_cut_with_an_ellipsis_and_cutting_again_changes_nothing(
    text: str,
) -> None:
    cut = shorten(text)
    if len(text) <= SHORTENED_AT:
        assert cut == text
    else:
        assert cut == text[:SHORTENED_AT] + "…"
    assert shorten(cut) == cut


# --- Labels -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "snapshot", "label"),
    [
        (RowKind.PART, {"name": "BME280"}, "BME280"),
        (RowKind.PIN, {"number": "3", "label": "SDA"}, "3 SDA"),
        (RowKind.PIN, {"number": "3", "label": None}, "3"),
        (RowKind.NET_PIN, {"designator": "U1", "pin": "3"}, "U1.3"),
        (RowKind.UNIT, {"code": "WX-U-0007"}, "WX-U-0007"),
        (RowKind.FLASH, {"unit_code": "WX-U-0007"}, "WX-U-0007"),
        (RowKind.VERSION, {"version": "1.2.0"}, "1.2.0"),
        (RowKind.SOURCE_FILE, {"path": "src/main.ino"}, "src/main.ino"),
        (RowKind.ATTACHMENT, {"title": "Datasheet"}, "Datasheet"),
        (RowKind.BOM_LINE, {"quantity": 4}, None),
        (RowKind.RUNS_ON, {"revision_id": str(uuid4())}, None),
    ],
)
def test_a_row_is_named_by_its_kinds_field(
    kind: RowKind, snapshot: dict[str, object], label: str | None
) -> None:
    assert RowChange(kind, Operation.INSERT, False, None, None, snapshot).label == label


def test_a_deleted_row_is_named_by_its_last_snapshot() -> None:
    row = RowChange(RowKind.NET, Operation.DELETE, False, None, {"name": "GND"}, None)
    assert row.label == "GND"


# --- Actions ----------------------------------------------------------------------------------


def test_what_happened_is_read_off_the_records_own_row() -> None:
    created = RowChange(RowKind.PART, Operation.INSERT, True, None, None, {"name": "R"})
    deleted = RowChange(RowKind.PART, Operation.DELETE, True, None, {"name": "R"}, None)
    trashed = an_update({"trashed_at": None}, {"trashed_at": "2026-10-01T09:00:00+00:00"})
    back = an_update({"trashed_at": "2026-10-01T09:00:00+00:00"}, {"trashed_at": None})
    renamed = an_update({"name": "R"}, {"name": "R 4k7"})
    pin = RowChange(RowKind.PIN, Operation.INSERT, False, None, None, {"number": "1"})

    assert a_change(created, pin).action is Action.CREATED
    assert a_change(deleted).action is Action.DELETED
    assert a_change(trashed).action is Action.MOVED_TO_TRASH
    assert a_change(back).action is Action.RESTORED_FROM_TRASH
    assert a_change(renamed).action is Action.EDITED
    assert a_change(renamed, reason=RESTORE_REASON).action is Action.RESTORED_VERSION
    # Only what it holds changed: still an edit of the record.
    assert a_change(pin).action is Action.EDITED


# --- What narrows the feed -------------------------------------------------------------------


def test_no_filter_keeps_every_change() -> None:
    renamed = an_update({"name": "R"}, {"name": "R 4k7"})

    assert ActivityFilter().matches(a_change(renamed))
    assert ActivityFilter(text=" \t ").text is None


def test_a_kind_keeps_the_changes_to_records_of_that_kind() -> None:
    renamed = a_change(an_update({"name": "R"}, {"name": "R 4k7"}))

    assert ActivityFilter(kind=RecordKind.PART).matches(renamed)
    assert not ActivityFilter(kind=RecordKind.PROJECT).matches(renamed)


def test_an_action_keeps_the_changes_that_did_it() -> None:
    trashed = a_change(an_update({"trashed_at": None}, {"trashed_at": "2026-10-01T09:00:00Z"}))

    assert ActivityFilter(action=Action.MOVED_TO_TRASH).matches(trashed)
    assert not ActivityFilter(action=Action.EDITED).matches(trashed)


def test_a_text_matches_the_records_name_ignoring_case() -> None:
    renamed = a_change(an_update({"name": "R"}, {"name": "R 4k7"}))
    unnamed = Change(ChangeId(8), AT, None, None, RecordRef(RecordKind.PART, uuid4(), None), (), 0)

    assert ActivityFilter(text="  kΩ  1% ").matches(renamed)
    assert not ActivityFilter(text="capacitor").matches(renamed)
    assert not ActivityFilter(text="k").matches(unnamed)


def test_a_text_longer_than_its_box_is_refused() -> None:
    with pytest.raises(InvalidHistoryFilterError):
        ActivityFilter(text="x" * (MAX_FILTER_TEXT_LENGTH + 1))


def test_a_change_counts_the_rows_it_doesnt_show() -> None:
    pin = RowChange(RowKind.PIN, Operation.INSERT, False, None, None, {"number": "1"})
    assert a_change(pin, count=45).more_rows == 44
    assert a_change(pin).more_rows == 0
    assert a_change(pin).own_row is None


# --- Cursor and pages (property 2) -----------------------------------------------------------


@given(st.integers(min_value=1, max_value=2**63 - 1))
def test_a_cursor_reads_back(value: int) -> None:
    cursor = ChangeCursor(ChangeId(value))
    assert ChangeCursor.decode(cursor.encode()) == cursor


@pytest.mark.parametrize(
    "text", ["", "0", "-1", "1.5", "abc", "١٢", "9" * MAX_CURSOR_LENGTH, "1" * 20, " 12"]
)
def test_a_cursor_the_api_didnt_give_is_refused(text: str) -> None:
    with pytest.raises(InvalidHistoryCursorError):
        ChangeCursor.decode(text)


def test_a_page_says_where_the_next_starts_only_when_one_exists() -> None:
    changes = [Change(ChangeId(number), AT, None, None, PART, (), 0) for number in (9, 8, 7)]
    assert HistoryPage.of(changes, 2) == HistoryPage(tuple(changes[:2]), ChangeCursor(ChangeId(8)))
    assert HistoryPage.of(changes, 3) == HistoryPage(tuple(changes), None)
    assert HistoryPage.of([], 50) == HistoryPage((), None)
