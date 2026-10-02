"""Finding parts and categories by typed text over the in-memory catalog (19-command-palette).

The SQL's own share, one statement over the trigram indexes, the wildcards as typed and the
other bench left out, is `tests/integration/test_find_reads.py`'s.
"""

import pytest

from support.catalog import BENCH, World
from wiredex.catalog.application.find import FindCategories, FindParts
from wiredex.catalog.domain.part import PartDefinition, PartDetails
from wiredex.catalog.domain.values import Manufacturer, Mpn, PartName

pytestmark = pytest.mark.anyio


def a_part(world: World, name: str, *, mpn: str | None = None, maker: str | None = None) -> None:
    part = world.add_part(world.resistors, name)
    part.revise(
        PartDetails(
            PartName(name),
            None if maker is None else Manufacturer(maker),
            None if mpn is None else Mpn(mpn),
        ),
        part.attributes,
        world.clock.now(),
    )


def names(found: list[PartDefinition]) -> list[str]:
    return [str(part.name) for part in found]


class TestFindParts:
    async def test_matches_the_name_the_mpn_or_the_manufacturer_case_aside(self) -> None:
        # Requirement 1.1.
        world = World()
        a_part(world, "Resistor 4k7")
        a_part(world, "Thin film", mpn="RES-0805")
        a_part(world, "Sensor", maker="Resolute Inc")
        a_part(world, "Capacitor 100n")
        find = FindParts(world.catalog.for_workspace)

        found = await find(BENCH, "RES", 10)

        assert sorted(names(found)) == ["Resistor 4k7", "Sensor", "Thin film"]
        assert world.catalog.opened_for == [BENCH]

    async def test_the_names_starting_with_the_text_come_first_then_by_name(self) -> None:
        # Requirement 1.3: "res" starts two names, then the one it only appears in.
        world = World()
        a_part(world, "Pressure sensor")
        a_part(world, "resonator 16 MHz")
        a_part(world, "Resistor 10k")
        find = FindParts(world.catalog.for_workspace)

        assert names(await find(BENCH, "res", 10)) == [
            "Resistor 10k",
            "resonator 16 MHz",
            "Pressure sensor",
        ]

    async def test_answers_at_most_the_limit(self) -> None:
        world = World()
        for index in range(5):
            a_part(world, f"Resistor {index}")
        find = FindParts(world.catalog.for_workspace)

        assert names(await find(BENCH, "resistor", 2)) == ["Resistor 0", "Resistor 1"]

    async def test_a_blank_text_finds_nothing_and_opens_nothing(self) -> None:
        world = World()
        a_part(world, "Resistor 4k7")
        find = FindParts(world.catalog.for_workspace)

        assert await find(BENCH, "   ", 10) == []
        assert world.catalog.opened_for == []

    async def test_the_text_is_trimmed(self) -> None:
        world = World()
        a_part(world, "Resistor 4k7")
        find = FindParts(world.catalog.for_workspace)

        assert names(await find(BENCH, "  4k7 ", 10)) == ["Resistor 4k7"]

    async def test_a_part_in_the_trash_is_never_found(self) -> None:
        # Requirement 2.1 (16-soft-delete-and-trash, decision 2).
        world = World()
        a_part(world, "Resistor 4k7")
        gone = world.add_part(world.resistors, "Resistor 10k")
        await world.delete_part(BENCH, gone.id)
        find = FindParts(world.catalog.for_workspace)

        assert names(await find(BENCH, "resistor", 10)) == ["Resistor 4k7"]


class TestFindCategories:
    async def test_matches_the_name_starting_ones_first(self) -> None:
        # Requirements 1.1 and 1.3, over the bench's Passives and Resistors and two more.
        world = World()
        world.add_category("Boards")
        world.add_category("Sensors", world.passives)
        find = FindCategories(world.catalog.for_workspace)

        found = await find(BENCH, "s", 10)

        assert [str(category.name) for category in found] == [
            "Sensors",
            "Boards",
            "Passives",
            "Resistors",
        ]

    async def test_answers_at_most_the_limit_and_nothing_for_a_blank_text(self) -> None:
        world = World()
        find = FindCategories(world.catalog.for_workspace)

        assert [str(category.name) for category in await find(BENCH, "s", 1)] == ["Passives"]
        assert await find(BENCH, "", 10) == []
