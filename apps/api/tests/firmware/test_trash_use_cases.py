"""Firmware's share of the trash over the in-memory firmware (16-soft-delete-and-trash).

Moving a firmware to the trash is `DeleteFirmware`, whose refusals `test_firmware_use_cases.py`
covers; here is what follows it: the trash's page, restoring, deleting for good and emptying, and
what a firmware in the trash still holds (its name, its versions).
"""

from datetime import timedelta
from uuid import uuid7

import pytest

from support.firmware import BENCH, World
from wiredex.firmware.application.trash import (
    DeleteFirmwareForGood,
    EmptyFirmwareTrash,
    ListTrashedFirmware,
    RestoreFirmware,
)
from wiredex.firmware.domain.errors import (
    FirmwareNotFoundError,
    FirmwareRefusal,
    NameInTrashError,
    VersionNotFoundError,
)
from wiredex.firmware.domain.firmware import Firmware, FirmwareDetails
from wiredex.firmware.domain.values import BoardTarget, FirmwareId, FirmwareName, Framework
from wiredex.shared_kernel.domain.trash import TrashedSlice

pytestmark = pytest.mark.anyio


async def a_trashed_firmware(world: World, name: str) -> Firmware:
    firmware = world.hold_firmware(name)
    world.clock.advance(timedelta(minutes=1))
    await world.delete_firmware(BENCH, firmware.id)
    return firmware


async def test_the_trash_lists_its_newest_firmware_with_how_many_match() -> None:
    world = World()
    first = await a_trashed_firmware(world, "Weather station")
    second = await a_trashed_firmware(world, "Greenhouse controller")
    third = await a_trashed_firmware(world, "Pico blink")
    listed = ListTrashedFirmware(world.work.for_workspace)

    assert await listed(BENCH, 2) == TrashedSlice((third, second), 3)
    assert await listed(BENCH, 50) == TrashedSlice((third, second, first), 3)
    assert await listed(BENCH, 50, "station") == TrashedSlice((first,), 1)
    assert await listed(BENCH, 50, "%") == TrashedSlice((), 0)


async def test_a_text_matches_a_firmwares_target_too() -> None:
    world = World()
    pico = world.hold_firmware("Blink", target="rp2040:rp2040:rpipico")
    world.clock.advance(timedelta(minutes=1))
    await world.delete_firmware(BENCH, pico.id)
    await a_trashed_firmware(world, "Weather station")
    listed = ListTrashedFirmware(world.work.for_workspace)

    assert await listed(BENCH, 50, "RPIPICO") == TrashedSlice((pico,), 1)


async def test_a_firmware_in_the_trash_takes_its_versions_out_of_reach() -> None:
    # Requirement 2.1: its versions are absent with it, and nothing can be started on it.
    world = World()
    firmware = world.hold_firmware("Weather station")
    version = world.hold_version(firmware, "1.0.0", released=True)
    await world.delete_firmware(BENCH, firmware.id)

    with pytest.raises(VersionNotFoundError):
        await world.get_version(BENCH, version.id)
    with pytest.raises(FirmwareNotFoundError):
        await world.start_version(BENCH, firmware.id)
    assert await world.list_firmware(BENCH, "") == []


async def test_a_restored_firmware_is_back_with_its_versions() -> None:
    world = World()
    firmware = world.hold_firmware("Weather station")
    version = world.hold_version(firmware, "1.0.0", released=True)
    await world.delete_firmware(BENCH, firmware.id)

    await RestoreFirmware(world.work.for_workspace)(BENCH, firmware.id)

    page = await world.get_firmware(BENCH, firmware.id)
    assert [summary.version.id for summary in page.versions] == [version.id]
    assert not firmware.in_trash


async def test_only_a_firmware_in_the_trash_is_restored_or_deleted_for_good() -> None:
    # Requirements 5.3 and 6.2: a live firmware and an unknown one are both not in the trash.
    world = World()
    live = world.hold_firmware("Weather station")
    work = world.work.for_workspace

    for missing in (live.id, FirmwareId(uuid7())):
        with pytest.raises(FirmwareNotFoundError, match="isn't in the trash"):
            await RestoreFirmware(work)(BENCH, missing)
        with pytest.raises(FirmwareNotFoundError, match="isn't in the trash"):
            await DeleteFirmwareForGood(work)(BENCH, missing)

    assert live.id in world.work.firmwares.saved
    assert world.work.commits == 0


async def test_emptying_the_trash_deletes_only_what_is_in_it() -> None:
    world = World()
    trashed = [await a_trashed_firmware(world, name) for name in ("Weather station", "Pico")]
    world.hold_version(trashed[0], "1.0.0", released=True)
    live = world.hold_firmware("Greenhouse controller")

    emptied = await EmptyFirmwareTrash(world.work.for_workspace)(BENCH)

    assert emptied == len(trashed)
    assert list(world.work.firmwares.saved) == [live.id]
    assert world.work.versions.saved == {}


async def test_a_firmware_in_the_trash_keeps_its_name_with_a_code_of_its_own() -> None:
    # Requirement 3.1: the browser says the holder is in the trash.
    world = World()
    await a_trashed_firmware(world, "Weather station")
    details = FirmwareDetails(
        FirmwareName("weather STATION"), BoardTarget("esp32:esp32:esp32"), Framework.ARDUINO
    )

    with pytest.raises(NameInTrashError, match="Weather station, in the trash") as refused:
        await world.create_firmware(BENCH, details)

    assert refused.value.code is FirmwareRefusal.NAME_IN_TRASH
    assert refused.value.item == "weather STATION"
