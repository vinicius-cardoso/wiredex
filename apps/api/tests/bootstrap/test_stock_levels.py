"""`InventoryStockLevels` over the in-memory inventory: available stock in projects' words.

The adapter drives a real `AvailableStock` over the inventory fakes, as the composition root
drives it over Postgres.
"""

from uuid import uuid7

import pytest

from support.inventory import BENCH, LOT_COUNTED_PART, UNIT_TRACKED_PART, World
from wiredex.bootstrap.projects import InventoryStockLevels
from wiredex.inventory.application.stock import AvailableStock
from wiredex.inventory.application.units import NewUnit, UnitReceipt
from wiredex.projects.domain.values import PartId
from wiredex.projects.domain.values import WorkspaceId as ProjectsWorkspaceId

pytestmark = pytest.mark.anyio

# The inventory's bench, as projects names it: the same UUID under projects' own type.
PROJECTS_BENCH = ProjectsWorkspaceId(BENCH)


def stock_levels(world: World) -> InventoryStockLevels:
    return InventoryStockLevels(AvailableStock(world.inventory.for_workspace))


async def test_each_part_answers_what_is_available_over_its_lots() -> None:
    world = World()
    world.hold_lot(LOT_COUNTED_PART, world.lab, on_hand=150)
    world.hold_lot(LOT_COUNTED_PART, world.drawer, on_hand=30)
    resistor, gone = PartId(LOT_COUNTED_PART), PartId(uuid7())

    available = await stock_levels(world).available(PROJECTS_BENCH, [resistor, gone])

    # A part no lot holds is left out, which the report reads as none available.
    assert available == {resistor: 180}
    # Asked in the caller's workspace, translated into inventory's.
    assert world.inventory.opened_for == [BENCH]


async def test_a_unit_tracked_part_answers_its_in_stock_units() -> None:
    # 09's requirement 6.3.
    world = World()
    await world.receive_units(
        BENCH, UnitReceipt(UNIT_TRACKED_PART, world.drawer.id, (NewUnit(),) * 3)
    )
    board = PartId(UNIT_TRACKED_PART)

    assert await stock_levels(world).available(PROJECTS_BENCH, [board]) == {board: 3}


async def test_no_parts_ask_nothing() -> None:
    world = World()

    assert await stock_levels(world).available(PROJECTS_BENCH, []) == {}
    assert world.inventory.opened_for == []
