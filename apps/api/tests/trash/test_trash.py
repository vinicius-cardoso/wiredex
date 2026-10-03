import base64
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st

from wiredex.shared_kernel.domain.trash import TrashPosition
from wiredex.trash.domain.errors import InvalidTrashCursorError, InvalidTrashFilterError
from wiredex.trash.domain.trash import (
    MAX_CURSOR_LENGTH,
    MAX_FILTER_TEXT_LENGTH,
    TrashCursor,
    TrashedItem,
    TrashFilter,
    TrashKind,
    TrashPage,
    merge,
)

START = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


def an_item(kind: TrashKind, minutes: int, item_id: UUID | None = None) -> TrashedItem:
    return TrashedItem(
        kind, item_id or uuid4(), f"{kind} {minutes}", None, START + timedelta(minutes=minutes)
    )


# A few distinct minutes, so ties on the time are common and the id has to break them.
items = st.lists(
    st.builds(an_item, st.sampled_from(TrashKind), st.integers(min_value=0, max_value=5)),
    max_size=30,
)


def newest_first(found: Sequence[TrashedItem]) -> list[TrashedItem]:
    return sorted(found, key=lambda item: item.position, reverse=True)


def page_of(held: Sequence[TrashedItem], cursor: TrashCursor | None, limit: int) -> TrashPage:
    """What `ListTrash` does with one bin per kind: each kind's newest `limit + 1` before the
    cursor, then the merge."""
    pages = []
    for kind in TrashKind:
        before = [
            item
            for item in newest_first(held)
            if item.kind is kind and (cursor is None or item.position < cursor.position)
        ]
        pages.append(before[: limit + 1])
    return merge(pages, limit)


def read_all(
    held: list[TrashedItem], limits: Sequence[int], removed_between: Sequence[int] = ()
) -> list[TrashedItem]:
    """Every page in turn until there is no cursor, removing a record between two pages when
    `removed_between` names one, as a restore or a delete for good meanwhile would."""
    read: list[TrashedItem] = []
    cursor: TrashCursor | None = None
    for step in range(len(held) + 2):
        page = page_of(held, cursor, limits[step % len(limits)])
        read.extend(page.items)
        if step < len(removed_between) and held:
            held.pop(removed_between[step] % len(held))
        if page.next is None:
            return read
        cursor = page.next
    pytest.fail("the trash never ran out of pages")


@given(items, st.lists(st.integers(min_value=1, max_value=7), min_size=1, max_size=5))
def test_the_trash_reads_every_record_once_newest_first(
    held: list[TrashedItem], limits: list[int]
) -> None:
    # Property 1.
    assert read_all(list(held), limits) == newest_first(held)


@given(
    items,
    st.lists(st.integers(min_value=1, max_value=7), min_size=1, max_size=5),
    st.lists(st.integers(min_value=0), max_size=5),
)
def test_a_record_removed_between_pages_is_never_read_twice(
    held: list[TrashedItem], limits: list[int], removed: list[int]
) -> None:
    # Property 2: no record twice, in order, and every record that stayed.
    remaining = list(held)
    read = read_all(remaining, limits, removed)
    assert len({item.id for item in read}) == len(read)
    assert read == newest_first(read)
    assert {item.id for item in remaining} <= {item.id for item in read}


@given(st.datetimes(timezones=st.just(UTC)), st.uuids())
def test_a_cursor_reads_back(moment: datetime, item_id: UUID) -> None:
    # Property 3.
    cursor = TrashCursor(TrashPosition(moment, item_id))
    assert TrashCursor.decode(cursor.encode()) == cursor


SOME_ID = "0199aaaa-0000-7000-8000-000000000001"


def encoded(raw: str | bytes) -> str:
    return base64.urlsafe_b64encode(raw if isinstance(raw, bytes) else raw.encode()).decode()


@pytest.mark.parametrize(
    "text",
    [
        "",
        "not base64 at all!",
        encoded("2026-10-01T09:00:00+00:00"),
        encoded(f"yesterday|{SOME_ID}"),
        encoded("2026-10-01T09:00:00+00:00|not-a-uuid"),
        encoded(f"2026-10-01T09:00:00+00:00|{SOME_ID}|more"),
        # A time with no offset: the API never answers one.
        encoded(f"2026-10-01T09:00:00|{SOME_ID}"),
        encoded(b"\xff\xfe|"),
        "A" * (MAX_CURSOR_LENGTH + 1),
    ],
)
def test_a_cursor_the_api_didnt_give_is_refused(text: str) -> None:
    with pytest.raises(InvalidTrashCursorError):
        TrashCursor.decode(text)


def test_records_moved_in_one_instant_order_by_id_across_kinds() -> None:
    first = an_item(TrashKind.PROJECT, 0, UUID("0199aaaa-0000-7000-8000-000000000001"))
    second = an_item(TrashKind.PART, 0, UUID("0199aaaa-0000-7000-8000-000000000002"))
    page = merge([[first], [second]], limit=1)
    assert page.items == (second,)
    assert page.next == TrashCursor(second.position)
    assert merge([[first]], limit=1).next is None


def test_an_empty_trash_is_one_empty_page() -> None:
    assert merge([[], [], [], []], limit=50) == TrashPage((), None)


# --- What narrows the list --------------------------------------------------------------


def a_named(kind: TrashKind, name: str, detail: str | None = None) -> TrashedItem:
    return TrashedItem(kind, uuid4(), name, detail, START)


def test_no_filter_keeps_every_record() -> None:
    assert TrashFilter().matches(a_named(TrashKind.UNIT, "WX-U-0001"))
    assert TrashFilter(text="   ").text is None


def test_a_kind_keeps_its_own_records_alone() -> None:
    wanted = TrashFilter(kind=TrashKind.FIRMWARE)

    assert wanted.keeps(TrashKind.FIRMWARE)
    assert not wanted.keeps(TrashKind.PART)
    assert not wanted.matches(a_named(TrashKind.PART, "Station"))


@pytest.mark.parametrize(
    ("name", "detail"),
    [("Weather STATION", None), ("WX-U-0003", "station board"), ("Rig", "the Station")],
)
def test_a_text_matches_the_name_or_the_detail_ignoring_case(name: str, detail: str | None) -> None:
    assert TrashFilter(text=" station ").matches(a_named(TrashKind.UNIT, name, detail))


def test_a_text_neither_holds_doesnt_match() -> None:
    assert not TrashFilter(text="station").matches(a_named(TrashKind.PART, "BME280", "BME-1"))


def test_a_text_and_a_kind_both_have_to_hold() -> None:
    wanted = TrashFilter(kind=TrashKind.PROJECT, text="station")

    assert wanted.matches(a_named(TrashKind.PROJECT, "Weather station"))
    assert not wanted.matches(a_named(TrashKind.FIRMWARE, "Weather station"))


def test_a_text_longer_than_its_box_is_refused() -> None:
    with pytest.raises(InvalidTrashFilterError):
        TrashFilter(text="x" * (MAX_FILTER_TEXT_LENGTH + 1))
