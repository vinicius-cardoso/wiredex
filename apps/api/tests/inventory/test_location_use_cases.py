"""The location use cases, over the in-memory inventory fakes.

The `World` seeds *Lab (WX-L-0001) → Drawer 3 (WX-L-0002)* straight into the stores, so a
test of one use case never leans on another one working.
"""

import pytest

from support.inventory import BENCH, LOT_COUNTED_PART, UNIT_TRACKED_PART, World
from wiredex.inventory.application.locations import (
    CreateLocation,
    DeleteLocation,
    ListLocations,
    MoveLocation,
    RenameLocation,
)
from wiredex.inventory.application.ports import NewLocation
from wiredex.inventory.domain.errors import (
    CircularLocationError,
    DuplicateLocationNameError,
    LocationInUseError,
)
from wiredex.inventory.domain.location import MAX_LOCATION_DEPTH, LocationTooDeepError
from wiredex.inventory.domain.values import LocationName

pytestmark = pytest.mark.anyio


def _create(world: World) -> CreateLocation:
    return CreateLocation(world.inventory.for_workspace, world.clock, world.ids)


async def test_duplicate_sibling_name_is_rejected() -> None:
    world = World()
    create = _create(world)
    with pytest.raises(DuplicateLocationNameError):
        await create(BENCH, NewLocation(LocationName("Drawer 3"), parent_id=world.lab.id))


async def test_two_roots_with_the_same_name_are_rejected() -> None:
    world = World()
    create = _create(world)
    with pytest.raises(DuplicateLocationNameError):
        # "Lab" is already a root; a second root of the same name is a duplicate sibling.
        await create(BENCH, NewLocation(LocationName("Lab")))


async def test_moving_under_own_descendant_is_a_cycle() -> None:
    world = World()
    move = MoveLocation(world.inventory.for_workspace)
    with pytest.raises(CircularLocationError):
        # Lab is the parent of Drawer 3; moving Lab under Drawer 3 would cut the tree loose.
        await move(BENCH, world.lab.id, world.drawer.id)


async def test_creating_past_the_depth_cap_is_rejected() -> None:
    world = World()
    create = _create(world)
    # Lab (1) → Drawer 3 (2); extend to the cap, then one past it.
    parent = world.drawer
    for level in range(3, MAX_LOCATION_DEPTH + 1):
        parent = await create(BENCH, NewLocation(LocationName(f"Level {level}"), parent.id))
    with pytest.raises(LocationTooDeepError):
        await create(BENCH, NewLocation(LocationName("Too deep"), parent.id))


async def test_delete_refuses_a_location_with_children() -> None:
    world = World()
    delete = DeleteLocation(world.inventory.for_workspace)
    with pytest.raises(LocationInUseError):
        await delete(BENCH, world.lab.id)


async def test_delete_refuses_a_location_holding_lots() -> None:
    world = World()
    leaf = world.add_location("Bin", world.drawer)
    world.hold_lot(LOT_COUNTED_PART, leaf, on_hand=5)
    delete = DeleteLocation(world.inventory.for_workspace)
    with pytest.raises(LocationInUseError):
        await delete(BENCH, leaf.id)


async def test_delete_succeeds_for_an_empty_leaf() -> None:
    world = World()
    delete = DeleteLocation(world.inventory.for_workspace)
    await delete(BENCH, world.drawer.id)
    assert await world.inventory.locations.get(world.drawer.id) is None
    assert world.inventory.commits == 1


async def test_noop_rename_does_not_commit() -> None:
    world = World()
    rename = RenameLocation(world.inventory.for_workspace)
    before = world.inventory.commits
    await rename(BENCH, world.drawer.id, LocationName("Drawer 3"))
    assert world.inventory.commits == before


async def test_create_mints_one_incrementing_code_and_commits_once() -> None:
    world = World()
    create = _create(world)
    # The seed writes Lab and Drawer 3 straight to the stores, so they don't draw from the
    # counter; the first minted code is WX-L-0001, and each create advances it by one.
    location = await create(BENCH, NewLocation(LocationName("Shelf")))
    assert location.code.value == "WX-L-0001"
    assert world.inventory.commits == 1
    second = await create(BENCH, NewLocation(LocationName("Cabinet")))
    assert second.code.value == "WX-L-0002"
    assert world.inventory.commits == 2


async def test_list_locations_carries_child_and_lot_counts() -> None:
    world = World()
    world.hold_lot(LOT_COUNTED_PART, world.drawer, on_hand=3)
    world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=1)
    listing = ListLocations(world.inventory.for_workspace)
    nodes = {node.location.id: node for node in await listing(BENCH)}
    assert nodes[world.lab.id].child_count == 1
    assert nodes[world.lab.id].lot_count == 0
    assert nodes[world.drawer.id].child_count == 0
    # The real number of lots, not only whether there are any.
    assert nodes[world.drawer.id].lot_count == 2
