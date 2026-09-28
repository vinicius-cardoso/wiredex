"""The inventory fakes stand up: the seeded world builds and the Parts port answers every kind.

The repositories and use-case behaviour are exercised by the use-case tests that consume this
support module; here we only prove the seed is coherent, so those tests start from solid
ground.
"""

from uuid import uuid7

import pytest

from support.inventory import (
    CONSUMABLE_PART,
    LOT_COUNTED_PART,
    TRACKED_CONSUMABLE_PART,
    UNIT_TRACKED_PART,
    FakeParts,
    World,
)
from wiredex.inventory.application.ports import PartStockInfo
from wiredex.inventory.domain.unit import UnitStatus
from wiredex.inventory.domain.values import PartId, WorkspaceId

pytestmark = pytest.mark.anyio


def test_world_seeds_lab_with_a_drawer_under_it() -> None:
    world = World()

    assert world.lab.parent_id is None
    assert world.drawer.parent_id == world.lab.id
    assert str(world.lab.code) == "WX-L-0001"
    assert str(world.drawer.code) == "WX-L-0002"
    assert set(world.inventory.locations.saved) == {world.lab.id, world.drawer.id}


async def test_fake_parts_answers_every_combination_of_flags() -> None:
    parts = FakeParts()
    workspace = WorkspaceId(uuid7())

    answers = {
        part_id: await parts.describe(workspace, part_id)
        for part_id in (
            LOT_COUNTED_PART,
            UNIT_TRACKED_PART,
            CONSUMABLE_PART,
            TRACKED_CONSUMABLE_PART,
        )
    }
    absent = await parts.describe(workspace, PartId(uuid7()))

    assert answers == {
        LOT_COUNTED_PART: PartStockInfo(True, tracked_individually=False, not_stocked=False),
        UNIT_TRACKED_PART: PartStockInfo(True, tracked_individually=True, not_stocked=False),
        CONSUMABLE_PART: PartStockInfo(True, tracked_individually=False, not_stocked=True),
        TRACKED_CONSUMABLE_PART: PartStockInfo(True, tracked_individually=True, not_stocked=True),
    }
    assert absent == PartStockInfo(exists=False, tracked_individually=False, not_stocked=False)


async def test_in_stock_at_counts_only_in_stock_units_of_the_lot() -> None:
    world = World()
    lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer)
    other_lot = world.hold_lot(UNIT_TRACKED_PART, world.lab)
    world.hold_unit(UNIT_TRACKED_PART, lot)
    world.hold_unit(UNIT_TRACKED_PART, lot)
    world.hold_unit(UNIT_TRACKED_PART, lot, status=UnitStatus.RETIRED)
    world.hold_unit(UNIT_TRACKED_PART, other_lot)

    # Two in_stock in the drawer's lot; the retired one and the unit in another lot don't count.
    assert await world.inventory.units.in_stock_at(lot.id) == 2
    assert await world.inventory.units.in_stock_at(other_lot.id) == 1
