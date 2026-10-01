"""Catalog's share of the trash over the in-memory catalog (16-soft-delete-and-trash).

Moving a part to the trash is `DeletePart`, whose refusals `test_part_use_cases.py` covers; here is
what follows it: the trash's page, restoring, deleting for good and emptying, and what a part in
the trash still holds (its MPN, its category).
"""

from datetime import timedelta
from uuid import uuid7

import pytest

from support.catalog import BENCH, World
from wiredex.catalog.application.parts import NewPart, PartRevision
from wiredex.catalog.application.ports import PartQuery
from wiredex.catalog.application.trash import (
    DeletePartForGood,
    EmptyPartTrash,
    ListTrashedParts,
    RestorePart,
)
from wiredex.catalog.domain.errors import (
    CategoryInUseError,
    DuplicateMpnError,
    PartNotFoundError,
)
from wiredex.catalog.domain.part import PartDefinition, PartDetails
from wiredex.catalog.domain.values import Manufacturer, Mpn, PartDefinitionId, PartName
from wiredex.shared_kernel.domain.trash import TrashPosition

pytestmark = pytest.mark.anyio

YAGEO = Manufacturer("Yageo")
MPN = Mpn("RC0805FR-074K7L")
# The bench's resistors require a resistance.
FOUR_K_SEVEN = {"resistance": "4k7"}


async def a_trashed_part(world: World, name: str = "R 4k7 0805") -> PartDefinition:
    part = world.add_part(world.resistors, name)
    world.clock.advance(timedelta(minutes=1))
    await world.delete_part(BENCH, part.id)
    return part


async def test_the_trash_lists_its_parts_newest_first_from_a_position() -> None:
    world = World()
    first = await a_trashed_part(world, "R 1k")
    second = await a_trashed_part(world, "R 2k")
    third = await a_trashed_part(world, "R 3k")
    world.add_part(world.resistors, "R 4k, still here")
    listed = ListTrashedParts(world.catalog.for_workspace)

    page = await listed(BENCH, None, 2)
    assert page == [third, second]
    assert second.trashed_at is not None
    rest = await listed(BENCH, TrashPosition(second.trashed_at, second.id), 2)
    assert rest == [first]


async def test_a_restored_part_is_back_where_it_was() -> None:
    world = World()
    part = await a_trashed_part(world)
    commits = world.catalog.commits

    await RestorePart(world.catalog.for_workspace)(BENCH, part.id)

    assert (await world.get_part(BENCH, part.id)).part is part
    assert not part.in_trash
    assert [found.id for found in (await world.list_parts(BENCH, PartQuery())).items] == [part.id]
    assert world.catalog.commits == commits + 1


async def test_only_a_part_in_the_trash_is_restored_or_deleted_for_good() -> None:
    # Requirements 5.3 and 6.2: a live part and an unknown one are both not in the trash.
    world = World()
    live = world.add_part(world.resistors)
    work = world.catalog.for_workspace

    for missing in (live.id, PartDefinitionId(uuid7())):
        with pytest.raises(PartNotFoundError, match="isn't in the trash"):
            await RestorePart(work)(BENCH, missing)
        with pytest.raises(PartNotFoundError, match="isn't in the trash"):
            await DeletePartForGood(work)(BENCH, missing)

    assert live.id in world.catalog.parts.saved
    assert world.catalog.commits == 0


async def test_a_part_deleted_for_good_is_gone() -> None:
    world = World()
    part = await a_trashed_part(world)

    await DeletePartForGood(world.catalog.for_workspace)(BENCH, part.id)

    assert part.id not in world.catalog.parts.saved
    assert await ListTrashedParts(world.catalog.for_workspace)(BENCH, None, 50) == []


async def test_emptying_the_trash_deletes_only_what_is_in_it() -> None:
    world = World()
    trashed = [await a_trashed_part(world, name) for name in ("R 1k", "R 2k")]
    live = world.add_part(world.resistors, "R 3k")

    emptied = await EmptyPartTrash(world.catalog.for_workspace)(BENCH)

    assert emptied == len(trashed)
    assert list(world.catalog.parts.saved) == [live.id]


async def test_a_part_in_the_trash_keeps_its_mpn() -> None:
    # Requirement 3.2: the unique index still holds it, and the refusal says where it is.
    world = World()
    part = await world.define_part(
        BENCH, NewPart(world.resistors.id, PartDetails(PartName("R 4k7"), YAGEO, MPN), FOUR_K_SEVEN)
    )
    await world.delete_part(BENCH, part.id)
    other = await world.define_part(
        BENCH, NewPart(world.resistors.id, PartDetails(PartName("R 4k7 1%")), FOUR_K_SEVEN)
    )

    with pytest.raises(DuplicateMpnError, match="R 4k7, in the trash"):
        await world.define_part(
            BENCH,
            NewPart(world.resistors.id, PartDetails(PartName("Another"), YAGEO, MPN), FOUR_K_SEVEN),
        )
    with pytest.raises(DuplicateMpnError, match="in the trash"):
        await world.update_part(
            BENCH,
            other.id,
            PartRevision(PartDetails(PartName("R 4k7 1%"), YAGEO, MPN), FOUR_K_SEVEN),
        )


async def test_a_category_whose_parts_are_in_the_trash_is_kept() -> None:
    # Requirement 7.1: a part in the trash is restored into its category.
    world = World()
    await a_trashed_part(world)

    with pytest.raises(CategoryInUseError, match="still has parts in the trash"):
        await world.delete_category(BENCH, world.resistors.id)

    assert world.resistors.id in world.catalog.categories.saved
