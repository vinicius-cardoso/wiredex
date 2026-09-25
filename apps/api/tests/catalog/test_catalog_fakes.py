"""The in-memory catalog the use-case tests run on, before there are use cases to run.

What is really under test is the annotation: mypy is what checks the fakes still satisfy
the ports, and a fake that has drifted takes every task after this one down with it.
"""

import pytest

from support.catalog import BENCH, InMemoryCatalog, World
from wiredex.catalog.application.ports import CatalogUnitOfWork

pytestmark = pytest.mark.anyio


async def test_the_fakes_stand_in_for_the_catalog_ports() -> None:
    work: CatalogUnitOfWork = InMemoryCatalog().for_workspace(BENCH)

    async with work as opened:
        assert await opened.categories.all() == []
        assert await opened.attribute_definitions.of_categories([]) == []
        assert await opened.parts.count_in([]) == 0


async def test_the_world_opens_a_bench_holding_resistors_under_passives() -> None:
    world = World()

    work = world.catalog.for_workspace(BENCH)

    assert [str(category.name) for category in await work.categories.all()] == [
        "Passives",
        "Resistors",
    ]
    assert await work.categories.ancestors(world.resistors.id) == [world.passives]
    assert await work.attribute_definitions.of_categories([world.resistors.id]) == [
        world.resistance
    ]
    # Seeding is not a transaction: a use-case test counts from zero.
    assert world.catalog.commits == 0
    assert world.catalog.opened_for == [BENCH]
