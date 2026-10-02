"""Finding units and locations by typed text over the in-memory inventory (19-command-palette).

The SQL's own share, one statement over the trigram indexes, the wildcards as typed and the
other bench left out, is `tests/integration/test_find_reads.py`'s.
"""

import pytest

from support.inventory import BENCH, UNIT_TRACKED_PART, World
from wiredex.inventory.application.find import FindLocations, FindUnits
from wiredex.inventory.domain.unit import UnitStatus
from wiredex.inventory.domain.values import Mac, Serial

pytestmark = pytest.mark.anyio


class TestFindUnits:
    async def test_matches_the_code_the_serial_or_the_mac_case_aside(self) -> None:
        # Requirement 1.1: three boards, each found by a different identity.
        world = World()
        lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=3)
        by_code = world.hold_unit(UNIT_TRACKED_PART, lot)
        by_serial = world.hold_unit(UNIT_TRACKED_PART, lot, serial=Serial("SN-0001-AB"))
        by_mac = world.hold_unit(UNIT_TRACKED_PART, lot, mac=Mac("02:00:00:00:00:01"))
        find = FindUnits(world.inventory.for_workspace)

        assert [unit.id for unit in await find(BENCH, "wx-u-0001", 10)] == [by_code.id]
        assert [unit.id for unit in await find(BENCH, "sn-0001", 10)] == [by_serial.id]
        assert [unit.id for unit in await find(BENCH, "00:01", 10)] == [by_mac.id]
        assert world.inventory.opened_for == [BENCH, BENCH, BENCH]

    async def test_answers_by_code_at_most_the_limit(self) -> None:
        world = World()
        lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=3)
        units = [world.hold_unit(UNIT_TRACKED_PART, lot) for _ in range(3)]
        find = FindUnits(world.inventory.for_workspace)

        found = await find(BENCH, "WX-U", 2)

        assert [unit.id for unit in found] == [units[0].id, units[1].id]

    async def test_a_blank_text_finds_nothing_and_opens_nothing(self) -> None:
        world = World()
        find = FindUnits(world.inventory.for_workspace)

        assert await find(BENCH, " ", 10) == []
        assert world.inventory.opened_for == []

    async def test_a_unit_in_the_trash_is_never_found(self) -> None:
        # Requirement 2.1 (16-soft-delete-and-trash, decision 2).
        world = World()
        lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=1)
        kept = world.hold_unit(UNIT_TRACKED_PART, lot)
        gone = world.hold_unit(UNIT_TRACKED_PART, lot, status=UnitStatus.RETIRED)
        await world.delete_unit(BENCH, gone.id)
        find = FindUnits(world.inventory.for_workspace)

        assert [unit.id for unit in await find(BENCH, "WX-U", 10)] == [kept.id]


class TestFindLocations:
    async def test_matches_the_name_or_the_code_starting_names_first(self) -> None:
        # Requirements 1.1 and 1.3, over the bench's Lab and Drawer 3 and two more.
        world = World()
        world.add_location("Shelf", world.lab)
        world.add_location("drawer 1", world.lab)
        find = FindLocations(world.inventory.for_workspace)

        assert [str(location.name) for location in await find(BENCH, "dra", 10)] == [
            "drawer 1",
            "Drawer 3",
        ]
        by_code = await find(BENCH, "wx-l-0001", 10)
        assert [str(location.name) for location in by_code] == ["Lab"]

    async def test_answers_at_most_the_limit_and_nothing_for_a_blank_text(self) -> None:
        world = World()
        find = FindLocations(world.inventory.for_workspace)

        assert [str(location.name) for location in await find(BENCH, "a", 1)] == ["Drawer 3"]
        assert await find(BENCH, "", 10) == []
