"""Finding firmware by typed text over the in-memory firmware (19-command-palette).

The SQL's own share, one statement, the wildcards as typed and the other bench left out, is
`tests/integration/test_find_reads.py`'s.
"""

import pytest

from support.firmware import BENCH, NOW, World
from wiredex.firmware.application.find import FindFirmware
from wiredex.firmware.domain.firmware import Firmware

pytestmark = pytest.mark.anyio


def names(found: list[Firmware]) -> list[str]:
    return [str(firmware.name) for firmware in found]


async def test_matches_the_name_or_the_target_case_aside() -> None:
    # Requirement 1.1: the station by its name, the logger by its board target.
    world = World()
    world.hold_firmware("Station sketch", target="esp32:esp32:esp32")
    world.hold_firmware("Logger", target="rp2040:rp2040:pico")
    find = FindFirmware(world.work.for_workspace)

    assert names(await find(BENCH, "SKETCH", 10)) == ["Station sketch"]
    assert names(await find(BENCH, "pico", 10)) == ["Logger"]


async def test_the_names_starting_with_the_text_come_first_then_by_name() -> None:
    # Requirement 1.3.
    world = World()
    for name in ("Old station", "station blink", "Station logger"):
        world.hold_firmware(name)
    find = FindFirmware(world.work.for_workspace)

    assert names(await find(BENCH, "station", 10)) == [
        "station blink",
        "Station logger",
        "Old station",
    ]


async def test_answers_at_most_the_limit_and_nothing_for_a_blank_text() -> None:
    world = World()
    for index in range(3):
        world.hold_firmware(f"Station {index}")
    find = FindFirmware(world.work.for_workspace)

    assert names(await find(BENCH, "station", 2)) == ["Station 0", "Station 1"]
    assert await find(BENCH, "", 10) == []


async def test_a_firmware_in_the_trash_is_never_found() -> None:
    # Requirement 2.1 (16-soft-delete-and-trash, decision 2).
    world = World()
    world.hold_firmware("Station sketch")
    world.hold_firmware("Station logger").move_to_trash(NOW)
    find = FindFirmware(world.work.for_workspace)

    assert names(await find(BENCH, "station", 10)) == ["Station sketch"]
