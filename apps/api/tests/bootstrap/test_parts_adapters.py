"""`CatalogParts` over the in-memory catalog: catalog's part descriptions in inventory's words.

The adapter drives a real `DescribeParts` over the catalog fakes, as the composition root
drives it over Postgres. The bench is the fakes' *Passives → Resistors*.
"""

from uuid import uuid7

import pytest

from support.catalog import BENCH, World
from wiredex.bootstrap.parts import CatalogParts
from wiredex.inventory.application.ports import PartStockInfo
from wiredex.inventory.domain.values import PartId
from wiredex.inventory.domain.values import WorkspaceId as InventoryWorkspaceId

pytestmark = pytest.mark.anyio

# The catalog's bench, as inventory names it: the same UUID under inventory's own type.
INVENTORY_BENCH = InventoryWorkspaceId(BENCH)


async def test_a_part_the_catalog_does_not_hold_does_not_exist() -> None:
    world = World()

    info = await CatalogParts(world.describe_parts).describe(INVENTORY_BENCH, PartId(uuid7()))

    assert info == PartStockInfo(exists=False, tracked_individually=False, not_stocked=False)


async def test_a_part_carries_both_flags_inherited_from_its_categories() -> None:
    # Passives sets not stocked and Resistors tracking: each resolves on its own (09's 1.3).
    world = World()
    world.passives.not_stocked = True
    world.resistors.tracked_individually = True
    part = world.add_part(world.resistors)

    info = await CatalogParts(world.describe_parts).describe(INVENTORY_BENCH, PartId(part.id))

    assert info == PartStockInfo(exists=True, tracked_individually=True, not_stocked=True)
    # Asked in the caller's workspace, translated into catalog's.
    assert world.catalog.opened_for == [BENCH]


async def test_a_part_under_a_tree_that_sets_nothing_is_stocked_and_lot_counted() -> None:
    world = World()
    part = world.add_part(world.resistors)

    info = await CatalogParts(world.describe_parts).describe(INVENTORY_BENCH, PartId(part.id))

    assert info == PartStockInfo(exists=True, tracked_individually=False, not_stocked=False)
