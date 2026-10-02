"""The trash's use cases over in-memory bins (16-soft-delete-and-trash, decision 8).

The list merges every bin's page newest first, asking each for one more record than it
answers; a write goes to the bin of its kind and no other; emptying asks every bin; and the
bins are asked one after the other, never at once, so a request holds one connection at a time.
"""

from uuid import uuid7

import pytest

from support.trash import BENCH, Trash, an_item
from wiredex.trash.domain.errors import TrashItemNotFoundError
from wiredex.trash.domain.trash import TrashCursor, TrashKind

pytestmark = pytest.mark.anyio


async def test_the_list_merges_every_kind_newest_first() -> None:
    trash = Trash()
    part, unit = an_item(TrashKind.PART, 1), an_item(TrashKind.UNIT, 4)
    project, firmware = an_item(TrashKind.PROJECT, 3), an_item(TrashKind.FIRMWARE, 2)
    trash.hold(part, unit, project, firmware)

    page = await trash.list_trash(BENCH, None, 50)

    assert [item.id for item in page.items] == [unit.id, project.id, firmware.id, part.id]
    assert page.next is None


async def test_each_bin_is_asked_for_one_more_than_the_page_from_the_cursor() -> None:
    trash = Trash()
    trash.hold(*(an_item(TrashKind.PART, minutes) for minutes in range(3)))
    trash.hold(an_item(TrashKind.FIRMWARE, 5))

    first = await trash.list_trash(BENCH, None, 2)
    assert first.next is not None
    second = await trash.list_trash(BENCH, first.next, 2)

    for trash_bin in trash.bins.values():
        assert trash_bin.asked == [(None, 3), (first.next.position, 3)]
    assert [item.trashed_at.minute for item in first.items] == [5, 2]
    assert [item.trashed_at.minute for item in second.items] == [1, 0]
    assert second.next is None


async def test_the_bins_are_asked_one_after_the_other() -> None:
    trash = Trash()
    trash.hold(an_item(TrashKind.UNIT, 1))

    await trash.list_trash(BENCH, None, 50)
    await trash.empty(BENCH)

    kinds = [kind.value for kind in TrashKind]
    assert trash.log == [f"page {kind}" for kind in kinds] + [f"empty {kind}" for kind in kinds]
    assert not trash.overlapped


async def test_an_empty_trash_is_an_empty_page() -> None:
    page = await Trash().list_trash(BENCH, None, 50)
    assert page.items == ()
    assert page.next is None


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
    assert (await trash.list_trash(BENCH, None, 50)).items == ()


async def test_a_cursor_reads_on_past_records_restored_meanwhile() -> None:
    # Requirement 4.3: nothing shifts, so no record is skipped or read twice.
    trash = Trash()
    items = [an_item(TrashKind.PROJECT, minutes) for minutes in range(5)]
    trash.hold(*items)
    first = await trash.list_trash(BENCH, None, 2)
    await trash.restore(BENCH, TrashKind.PROJECT, items[4].id)
    await trash.restore(BENCH, TrashKind.PROJECT, items[2].id)

    assert first.next is not None
    second = await trash.list_trash(BENCH, TrashCursor(first.next.position), 2)

    assert [item.id for item in first.items] == [items[4].id, items[3].id]
    assert [item.id for item in second.items] == [items[1].id, items[0].id]
