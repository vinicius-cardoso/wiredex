"""The trash's use cases over in-memory bins (16-soft-delete-and-trash, decision 8).

The list asks every kept bin for its newest matches up to the end of the page and merges them
newest first, adding up their totals; a write goes to the bin of its kind and no other; emptying
asks every bin; and the bins are asked one after the other, never at once, so a request holds
one connection at a time.
"""

from uuid import uuid7

import pytest

from support.trash import BENCH, Trash, an_item
from wiredex.shared_kernel.domain.paging import PageRequest
from wiredex.trash.domain.errors import TrashItemNotFoundError
from wiredex.trash.domain.trash import TrashFilter, TrashKind

pytestmark = pytest.mark.anyio


async def test_the_list_merges_every_kind_newest_first() -> None:
    trash = Trash()
    part, unit = an_item(TrashKind.PART, 1), an_item(TrashKind.UNIT, 4)
    project, firmware = an_item(TrashKind.PROJECT, 3), an_item(TrashKind.FIRMWARE, 2)
    trash.hold(part, unit, project, firmware)

    page = await trash.list_trash(BENCH, PageRequest())

    assert [item.id for item in page.items] == [unit.id, project.id, firmware.id, part.id]
    assert page.total == 4
    assert page.request == PageRequest()


async def test_each_bin_is_asked_once_for_the_pages_reach_with_the_text() -> None:
    trash = Trash()

    await trash.list_trash(BENCH, PageRequest(3, 10), TrashFilter(text="  BME280   breakout "))
    await trash.list_trash(BENCH, PageRequest(1, 25))

    for trash_bin in trash.bins.values():
        assert trash_bin.asked == [(30, "BME280 breakout"), (25, None)]


async def test_the_totals_of_the_bins_add_up() -> None:
    trash = Trash()
    trash.hold(*(an_item(TrashKind.PART, minutes) for minutes in range(3)))
    trash.hold(*(an_item(TrashKind.FIRMWARE, minutes) for minutes in range(3, 5)))
    trash.hold(an_item(TrashKind.UNIT, 9))

    first = await trash.list_trash(BENCH, PageRequest(1, 2))
    second = await trash.list_trash(BENCH, PageRequest(2, 2))
    third = await trash.list_trash(BENCH, PageRequest(3, 2))

    assert {first.total, second.total, third.total} == {6}
    assert [item.trashed_at.minute for item in first.items] == [9, 4]
    assert [item.trashed_at.minute for item in second.items] == [3, 2]
    assert [item.trashed_at.minute for item in third.items] == [1, 0]


async def test_the_bins_are_asked_one_after_the_other() -> None:
    trash = Trash()
    trash.hold(an_item(TrashKind.UNIT, 1))

    await trash.list_trash(BENCH, PageRequest(), TrashFilter(text="wx"))
    await trash.empty(BENCH)

    kinds = [kind.value for kind in TrashKind]
    assert trash.log == [f"newest {kind}" for kind in kinds] + [f"empty {kind}" for kind in kinds]
    assert not trash.overlapped


async def test_an_empty_trash_is_an_empty_first_page() -> None:
    page = await Trash().list_trash(BENCH, PageRequest(4, 50))
    assert page.items == ()
    assert page.total == 0
    assert page.request == PageRequest(1, 50)


async def test_a_page_emptied_by_restores_is_served_as_the_new_last_page() -> None:
    trash = Trash()
    items = [an_item(TrashKind.PROJECT, minutes) for minutes in range(3)]
    trash.hold(*items)
    await trash.restore(BENCH, TrashKind.PROJECT, items[0].id)

    page = await trash.list_trash(BENCH, PageRequest(2, 2))

    assert page.request == PageRequest(1, 2)
    assert [item.id for item in page.items] == [items[2].id, items[1].id]


@pytest.mark.parametrize("kind", list(TrashKind))
async def test_a_restore_goes_to_the_bin_of_its_kind(kind: TrashKind) -> None:
    trash = Trash()
    item, other = an_item(kind, 1), an_item(kind, 2)
    trash.hold(item, other, *(an_item(each, 3) for each in TrashKind if each is not kind))

    await trash.restore(BENCH, kind, item.id)

    assert trash.log == [f"restore {kind.value}"]
    assert item not in trash.held()
    assert other in trash.held()


@pytest.mark.parametrize("kind", list(TrashKind))
async def test_a_delete_for_good_goes_to_the_bin_of_its_kind(kind: TrashKind) -> None:
    trash = Trash()
    item = an_item(kind, 1)
    trash.hold(item)

    await trash.delete(BENCH, kind, item.id)

    assert trash.log == [f"delete {kind.value}"]
    assert trash.held() == []


async def test_a_record_named_as_another_kind_is_not_in_the_trash() -> None:
    # Requirement 5.3: the id is read only as the kind says, and nothing changes.
    trash = Trash()
    part = an_item(TrashKind.PART, 1)
    trash.hold(part)

    with pytest.raises(TrashItemNotFoundError):
        await trash.restore(BENCH, TrashKind.PROJECT, part.id)
    with pytest.raises(TrashItemNotFoundError):
        await trash.delete(BENCH, TrashKind.UNIT, part.id)
    assert trash.held() == [part]


async def test_a_record_not_in_the_trash_is_a_404() -> None:
    trash = Trash()
    with pytest.raises(TrashItemNotFoundError):
        await trash.restore(BENCH, TrashKind.FIRMWARE, uuid7())
    with pytest.raises(TrashItemNotFoundError):
        await trash.delete(BENCH, TrashKind.FIRMWARE, uuid7())


async def test_a_kind_with_no_bin_is_a_404() -> None:
    trash = Trash(kinds=[TrashKind.PART])
    with pytest.raises(TrashItemNotFoundError, match="nothing of that kind"):
        await trash.restore(BENCH, TrashKind.UNIT, uuid7())
    with pytest.raises(TrashItemNotFoundError, match="nothing of that kind"):
        await trash.delete(BENCH, TrashKind.UNIT, uuid7())
    assert trash.log == []


async def test_emptying_asks_every_bin() -> None:
    trash = Trash()
    trash.hold(*(an_item(kind, minutes) for minutes, kind in enumerate(TrashKind)))

    await trash.empty(BENCH)

    assert trash.held() == []
    assert (await trash.list_trash(BENCH, PageRequest())).items == ()


# --- Narrowed by a kind and a text ------------------------------------------------------


async def test_a_kind_asks_its_own_bin_alone() -> None:
    trash = Trash()
    part, unit = an_item(TrashKind.PART, 1), an_item(TrashKind.UNIT, 2)
    trash.hold(part, unit)

    page = await trash.list_trash(BENCH, PageRequest(), TrashFilter(kind=TrashKind.UNIT))

    assert [item.id for item in page.items] == [unit.id]
    assert page.total == 1
    assert trash.log == ["newest unit"]


async def test_a_text_matches_a_name_or_a_detail_ignoring_case() -> None:
    trash = Trash()
    by_name = an_item(TrashKind.PART, 1, name="BME280 breakout")
    by_detail = an_item(TrashKind.UNIT, 2, name="WX-U-0007", detail="BME280 breakout")
    other = an_item(TrashKind.PROJECT, 3, name="Weather station")
    trash.hold(by_name, by_detail, other)

    page = await trash.list_trash(BENCH, PageRequest(), TrashFilter(text="  bme280 "))

    assert [item.id for item in page.items] == [by_detail.id, by_name.id]
    assert page.total == 2


async def test_a_text_pages_its_matches_alone() -> None:
    # The matches sit apart, among many more records that don't match: the pages and the total
    # count the matches only.
    trash = Trash()
    others = [an_item(TrashKind.PART, minutes) for minutes in range(1, 251)]
    matches = [
        an_item(TrashKind.FIRMWARE, minutes, name=f"Station {minutes}") for minutes in (0, 120, 260)
    ]
    trash.hold(*others, *matches)
    station = TrashFilter(text="station")

    first = await trash.list_trash(BENCH, PageRequest(1, 2), station)
    second = await trash.list_trash(BENCH, PageRequest(2, 2), station)

    assert [item.name for item in first.items] == ["Station 260", "Station 120"]
    assert [item.name for item in second.items] == ["Station 0"]
    assert first.total == second.total == 3
    assert not trash.overlapped
