from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from math import ceil
from uuid import UUID, uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st

from wiredex.shared_kernel.domain.paging import Page, PageRequest
from wiredex.shared_kernel.domain.trash import TrashedSlice
from wiredex.trash.domain.errors import InvalidTrashFilterError
from wiredex.trash.domain.trash import (
    MAX_FILTER_TEXT_LENGTH,
    TrashedItem,
    TrashFilter,
    TrashKind,
    page_of,
)

START = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


def an_item(kind: TrashKind, minutes: int, item_id: UUID | None = None) -> TrashedItem:
    return TrashedItem(
        kind, item_id or uuid4(), f"{kind} {minutes}", None, START + timedelta(minutes=minutes)
    )


# A few distinct minutes, so ties on the time are common and the id has to break them.
items = st.lists(
    st.builds(an_item, st.sampled_from(TrashKind), st.integers(min_value=0, max_value=3)),
    max_size=40,
)


def newest_first(found: Sequence[TrashedItem]) -> list[TrashedItem]:
    return sorted(found, key=lambda item: item.position, reverse=True)


def served(held: Sequence[TrashedItem], request: PageRequest) -> Page[TrashedItem]:
    """What `ListTrash` does with one bin per kind: each kind's newest `reach` and its total,
    then `page_of`."""
    shares = []
    for kind in TrashKind:
        own = newest_first([item for item in held if item.kind is kind])
        shares.append(TrashedSlice(tuple(own[: request.reach]), len(own)))
    return page_of(shares, request)


@given(items, st.integers(min_value=1, max_value=10))
def test_walking_every_page_reads_each_record_once_newest_first(
    held: list[TrashedItem], size: int
) -> None:
    pages = max(1, ceil(len(held) / size))
    read: list[TrashedItem] = []
    for number in range(1, pages + 1):
        page = served(held, PageRequest(number, size))
        assert page.total == len(held)
        assert page.request == PageRequest(number, size)
        read.extend(page.items)
    assert read == newest_first(held)


@given(items, st.integers(min_value=1, max_value=10), st.integers(min_value=1, max_value=5))
def test_a_page_past_the_end_is_the_last_page(
    held: list[TrashedItem], size: int, beyond: int
) -> None:
    last = max(1, ceil(len(held) / size))

    page = served(held, PageRequest(last + beyond, size))

    assert page == served(held, PageRequest(last, size))
    assert page.request.number == last


def test_records_moved_in_one_instant_order_by_id_across_kinds() -> None:
    first = an_item(TrashKind.PROJECT, 0, UUID("0199aaaa-0000-7000-8000-000000000001"))
    second = an_item(TrashKind.PART, 0, UUID("0199aaaa-0000-7000-8000-000000000002"))
    shares = [TrashedSlice((first,), 1), TrashedSlice((second,), 1)]

    assert page_of(shares, PageRequest(1, 1)).items == (second,)
    assert page_of(shares, PageRequest(2, 1)).items == (first,)


def test_the_total_is_every_bins_total_not_what_it_answered() -> None:
    # A bin answers at most `reach` records, but counts every match.
    newest = an_item(TrashKind.UNIT, 3)
    page = page_of([TrashedSlice((newest,), 40), TrashedSlice((), 2)], PageRequest(1, 1))

    assert page == Page((newest,), 42, PageRequest(1, 1))


def test_an_empty_trash_is_one_empty_page() -> None:
    page = page_of([TrashedSlice((), 0)] * 4, PageRequest(3, 50))
    assert page == Page((), 0, PageRequest(1, 50))


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


def test_a_text_matches_with_lower_as_ilike_does_not_casefold() -> None:
    # The modules match in SQL with ILIKE, which lowers; casefold() would read "ß" as "ss".
    assert not TrashFilter(text="ss").matches(a_named(TrashKind.PROJECT, "Straße"))
    assert TrashFilter(text="STRASSE").matches(a_named(TrashKind.PROJECT, "strasse"))


def test_a_text_neither_holds_doesnt_match() -> None:
    assert not TrashFilter(text="station").matches(a_named(TrashKind.PART, "BME280", "BME-1"))


def test_a_text_and_a_kind_both_have_to_hold() -> None:
    wanted = TrashFilter(kind=TrashKind.PROJECT, text="station")

    assert wanted.matches(a_named(TrashKind.PROJECT, "Weather station"))
    assert not wanted.matches(a_named(TrashKind.FIRMWARE, "Weather station"))


def test_a_text_longer_than_its_box_is_refused() -> None:
    with pytest.raises(InvalidTrashFilterError):
        TrashFilter(text="x" * (MAX_FILTER_TEXT_LENGTH + 1))
