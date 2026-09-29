"""`CatalogParts` and `CatalogPartLookup` over the in-memory catalog: catalog's part
descriptions in inventory's words and in projects'.

The adapters drive a real `DescribeParts` over the catalog fakes, as the composition root
drives it over Postgres. The bench is the fakes' *Passives → Resistors*.
"""

from uuid import uuid7

import pytest

from support.catalog import BENCH, World
from wiredex.bootstrap.parts import CatalogPartLookup, CatalogParts
from wiredex.catalog.domain.values import Manufacturer, Mpn, Package
from wiredex.inventory.application.ports import PartStockInfo
from wiredex.inventory.domain.values import PartId
from wiredex.inventory.domain.values import WorkspaceId as InventoryWorkspaceId
from wiredex.projects.domain.shortage import PartFacts
from wiredex.projects.domain.values import PartId as ProjectsPartId
from wiredex.projects.domain.values import WorkspaceId as ProjectsWorkspaceId

pytestmark = pytest.mark.anyio

# The catalog's bench, as inventory names it: the same UUID under inventory's own type.
INVENTORY_BENCH = InventoryWorkspaceId(BENCH)
PROJECTS_BENCH = ProjectsWorkspaceId(BENCH)


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


# --- CatalogPartLookup: what a BOM's report says about its parts ------------------------------


async def test_the_lookup_describes_each_part_in_projects_words() -> None:
    world = World()
    world.passives.not_stocked = True
    part = world.add_part(world.resistors, "BME280")
    # Written straight onto the seed: the adapter only reads what the catalog holds.
    part.manufacturer = Manufacturer("Bosch Sensortec")
    part.mpn = Mpn("BME280")
    part.package = Package("LGA-8")
    wanted = ProjectsPartId(part.id)

    facts = await CatalogPartLookup(world.describe_parts).describe(PROJECTS_BENCH, [wanted])

    assert facts == {
        wanted: PartFacts(wanted, "BME280", "Bosch Sensortec", "BME280", "LGA-8", False, True)
    }
    assert world.catalog.opened_for[-1] == BENCH


async def test_the_lookup_leaves_out_a_part_the_catalog_doesnt_hold() -> None:
    # 09's requirement 9.3: absent, which projects reads as an unknown part.
    world = World()
    part = world.add_part(world.resistors)
    held, gone = ProjectsPartId(part.id), ProjectsPartId(uuid7())

    facts = await CatalogPartLookup(world.describe_parts).describe(PROJECTS_BENCH, [held, gone])

    assert set(facts) == {held}
    assert facts[held].name == "R 4k7 0805"
    assert (facts[held].manufacturer, facts[held].mpn, facts[held].package) == (None, None, None)


async def test_the_lookup_answers_nothing_for_no_parts() -> None:
    world = World()

    assert await CatalogPartLookup(world.describe_parts).describe(PROJECTS_BENCH, []) == {}
    assert world.catalog.opened_for == []
