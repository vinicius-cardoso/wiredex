"""The flash use cases over the in-memory firmware fakes: logging a flash, reading what a board
runs and removing an entry (15-flash-log).

The fakes write straight into their stores and count commits, so a refused flash is one that
left the stores as they were and committed nothing. The fakes hold one bench, so a unit or a
version they don't hold stands in for another bench's, as it does for 13's revisions.
"""

from dataclasses import replace
from datetime import datetime, timedelta
from uuid import uuid7

import pytest

from support.firmware import BENCH, NOW, World
from wiredex.firmware.application.ports import FlashEntry, FlashView, NewFlash
from wiredex.firmware.domain.errors import (
    FirmwareError,
    FlashedInFutureError,
    FlashNotFoundError,
    NotReleasedError,
    UnitNotFoundError,
    UnitRetiredError,
    VersionNotFoundError,
)
from wiredex.firmware.domain.firmware import Firmware
from wiredex.firmware.domain.flash import FlashNotes, UnitFacts
from wiredex.firmware.domain.values import FirmwareId, FlashId, Framework, UnitId, VersionId

pytestmark = pytest.mark.anyio

CHECKING = FlashNotes("Checking a new board")


def pico_blink(world: World) -> Firmware:
    return world.hold_firmware("Pico blink", target="RPI_PICO", framework=Framework.MICROPYTHON)


class TestLog:
    async def test_records_the_unit_the_version_the_time_and_the_notes_in_one_commit(
        self,
    ) -> None:
        # Requirements 1.1 and 1.8: the unit's code is copied, so the entry outlives the unit.
        # The answer is the entry as the log shows it.
        world = World()
        firmware = pico_blink(world)
        release = world.hold_version(firmware, "1.0.0", released=True)
        pico = world.units.hold()
        at = NOW - timedelta(hours=2)

        view = await world.log_flash(BENCH, pico.unit_id, NewFlash(release.id, at, CHECKING))

        flash = view.entry.flash
        assert world.work.flashes.saved == {flash.id: flash}
        assert (flash.workspace_id, flash.unit_id, flash.unit_code, flash.version_id) == (
            BENCH,
            pico.unit_id,
            pico.code,
            release.id,
        )
        assert (flash.flashed_at, flash.notes, flash.created_at) == (at, CHECKING, NOW)
        assert view == FlashView(
            FlashEntry(flash, firmware.id, firmware.name, release.number), None
        )
        assert world.work.opened_for == [BENCH]
        assert world.work.commits == 1

    async def test_locks_the_versions_firmware_before_the_unit(self) -> None:
        # Decision 9: 13's deletes take the same firmware lock, so the version can't go between
        # the check and the insert, and no writer takes a unit's lock before a firmware's.
        world = World()
        firmware = pico_blink(world)
        release = world.hold_version(firmware, "1.0.0", released=True)
        pico = world.units.hold()
        order: list[str] = []
        locked, lock = world.work.firmwares.locked, world.units.lock

        async def locking_firmware(firmware_id: FirmwareId) -> Firmware | None:
            order.append("firmware")
            return await locked(firmware_id)

        async def locking_unit(unit_id: UnitId) -> UnitFacts | None:
            order.append("unit")
            return await lock(unit_id)

        world.work.firmwares.locked = locking_firmware  # type: ignore[method-assign]
        world.units.lock = locking_unit  # type: ignore[method-assign]

        await world.log_flash(BENCH, pico.unit_id, NewFlash(release.id))

        assert order == ["firmware", "unit"]
        assert world.work.firmwares.locks == [firmware.id]
        assert world.units.locks == [pico.unit_id]

    async def test_a_flash_logged_without_a_time_was_flashed_now(self) -> None:
        # Requirement 1.2.
        world = World()
        release = world.hold_version(pico_blink(world), "1.0.0", released=True)

        view = await world.log_flash(BENCH, world.units.hold().unit_id, NewFlash(release.id))

        assert view.entry.flash.flashed_at == view.entry.flash.created_at == NOW
        assert view.entry.flash.notes is None

    async def test_a_held_unit_records_its_revision_and_keeps_it_after_a_cancel(self) -> None:
        # Requirement 1.7: a cancel clears the unit's revision, and the entry still names the
        # build the board was flashed in.
        world = World()
        release = world.hold_version(pico_blink(world), "1.0.0", released=True)
        greenhouse = world.directory.hold("Greenhouse controller", "A")
        esp32 = world.units.hold(revision_id=greenhouse.revision_id)

        logged = await world.log_flash(BENCH, esp32.unit_id, NewFlash(release.id))
        world.units.held[esp32.unit_id] = replace(esp32, revision_id=None)
        view = await world.get_unit_firmware(BENCH, esp32.unit_id)

        assert logged.revision == greenhouse
        assert view.unit.revision_id is None
        assert view.current == logged
        assert view.current.entry.flash.revision_id == greenhouse.revision_id


TOO_FAR_AHEAD = NOW + timedelta(minutes=5, seconds=1)


@pytest.mark.parametrize(
    ("unit", "version", "flashed_at", "refusal", "message"),
    [
        ("in stock", "draft", None, NotReleasedError, "1.1.0 is a draft"),  # 1.5
        ("retired", "release", None, UnitRetiredError, "WX-U-0002 is retired"),  # 1.6
        ("in stock", "release", TOO_FAR_AHEAD, FlashedInFutureError, "five minutes"),  # 1.4
        ("missing", "release", None, UnitNotFoundError, "that unit doesn't exist"),  # 1.10
        ("in stock", "missing", None, VersionNotFoundError, "that version doesn't exist"),
    ],
    ids=["draft", "retired unit", "too far ahead", "another bench's unit", "another's version"],
)
async def test_a_refused_flash_writes_nothing(
    unit: str,
    version: str,
    flashed_at: datetime | None,
    refusal: type[FirmwareError],
    message: str,
) -> None:
    world = World()
    firmware = pico_blink(world)
    versions = {
        "release": world.hold_version(firmware, "1.0.0", released=True).id,
        "draft": world.hold_version(firmware, "1.1.0").id,
        "missing": VersionId(uuid7()),
    }
    units = {
        "in stock": world.units.hold().unit_id,
        "retired": world.units.hold(retired=True).unit_id,
        "missing": UnitId(uuid7()),
    }
    before = world.snapshot()

    with pytest.raises(refusal, match=message):
        await world.log_flash(BENCH, units[unit], NewFlash(versions[version], flashed_at))

    assert world.snapshot() == before
    assert world.work.commits == 0


class TestUnitFirmware:
    async def test_answers_the_log_newest_first_its_current_version_and_the_newer_release(
        self,
    ) -> None:
        # Requirements 2.1 to 2.3: by when each was flashed, then logged, so the flash backdated
        # to two days ago takes its place without becoming current. Each recorded revision is
        # resolved in one read, and one the workspace lost is left out, the flash keeping it. A
        # draft above the latest release isn't a newer release.
        world = World()
        blink = pico_blink(world)
        first = world.hold_version(blink, "1.0.0", released=True)
        second = world.hold_version(blink, "1.1.0", released=True)
        world.hold_version(blink, "1.2.0")
        station = world.hold_firmware("Weather station")
        weather = world.hold_version(station, "0.1.0", released=True)
        greenhouse = world.directory.hold("Greenhouse controller", "A")
        lost = world.directory.hold("Weather station", "B")
        pico = world.units.hold()
        older = world.hold_flash(
            replace(pico, revision_id=lost.revision_id), second, flashed_at=NOW - timedelta(days=3)
        )
        current = world.hold_flash(
            replace(pico, revision_id=greenhouse.revision_id),
            first,
            flashed_at=NOW - timedelta(days=1),
        )
        backdated = world.hold_flash(pico, weather, flashed_at=NOW - timedelta(days=2))
        world.hold_flash(world.units.hold(), second)
        del world.directory.held[lost.revision_id]

        view = await world.get_unit_firmware(BENCH, pico.unit_id)

        assert view.unit == pico
        assert [(one.entry.flash, one.revision) for one in view.flashes] == [
            (current, greenhouse),
            (backdated, None),
            (older, None),
        ]
        assert [(one.entry.firmware_name, one.entry.number) for one in view.flashes] == [
            (blink.name, first.number),
            (station.name, weather.number),
            (blink.name, second.number),
        ]
        assert view.current is view.flashes[0]
        assert view.newer_release is second
        assert older.revision_id == lost.revision_id
        assert world.directory.asked == [(greenhouse.revision_id, lost.revision_id)]
        assert world.units.locks == []
        assert world.work.commits == 0

    async def test_a_board_on_the_latest_release_has_no_newer_one(self) -> None:
        world = World()
        blink = pico_blink(world)
        world.hold_version(blink, "1.0.0", released=True)
        latest = world.hold_version(blink, "1.1.0", released=True)
        pico = world.units.hold()
        world.hold_flash(pico, latest)

        view = await world.get_unit_firmware(BENCH, pico.unit_id)

        assert view.current is not None
        assert view.current.entry.number == latest.number
        assert view.newer_release is None

    async def test_a_unit_never_flashed_runs_nothing_known_and_asks_nothing_more(self) -> None:
        world = World()
        pico = world.units.hold()

        view = await world.get_unit_firmware(BENCH, pico.unit_id)

        assert (view.unit, view.flashes, view.current, view.newer_release) == (pico, (), None, None)
        assert world.directory.asked == []

    async def test_a_retired_units_log_reads_as_any_and_says_it_is_retired(self) -> None:
        # Requirement 2.4.
        world = World()
        release = world.hold_version(pico_blink(world), "1.0.0", released=True)
        pico = world.units.hold(retired=True)
        flash = world.hold_flash(pico, release)

        view = await world.get_unit_firmware(BENCH, pico.unit_id)

        assert view.unit.retired
        assert view.current is not None
        assert view.current.entry.flash == flash

    async def test_a_unit_not_in_the_workspace_is_not_found(self) -> None:
        # Requirement 2.5: a deleted unit's flashes stay (5.4), and its log is still a 404.
        world = World()
        release = world.hold_version(pico_blink(world), "1.0.0", released=True)
        pico = world.units.hold()
        flash = world.hold_flash(pico, release)
        del world.units.held[pico.unit_id]

        with pytest.raises(UnitNotFoundError, match="that unit doesn't exist"):
            await world.get_unit_firmware(BENCH, pico.unit_id)

        assert world.work.flashes.saved == {flash.id: flash}


class TestRemove:
    async def test_removing_the_newest_flash_makes_the_one_before_it_current(self) -> None:
        # Requirements 3.1 and 3.2: the entry was a mistake, so the board runs what it ran.
        world = World()
        blink = pico_blink(world)
        first = world.hold_version(blink, "1.0.0", released=True)
        second = world.hold_version(blink, "1.1.0", released=True)
        pico = world.units.hold()
        before = world.hold_flash(pico, first, flashed_at=NOW - timedelta(days=1))
        newest = world.hold_flash(pico, second)

        await world.remove_flash(BENCH, newest.id)
        view = await world.get_unit_firmware(BENCH, pico.unit_id)

        assert world.work.flashes.saved == {before.id: before}
        assert view.current is not None
        assert view.current.entry.flash == before
        assert view.newer_release is second
        assert world.work.commits == 1

    @pytest.mark.parametrize("gone", [False, True], ids=["retired", "deleted"])
    async def test_removes_a_flash_whatever_its_unit_became(self, gone: bool) -> None:
        # Requirement 3.1: a deleted unit's entries are cleared here, since its page is gone.
        world = World()
        release = world.hold_version(pico_blink(world), "1.0.0", released=True)
        pico = world.units.hold()
        flash = world.hold_flash(pico, release)
        if gone:
            del world.units.held[pico.unit_id]
        else:
            world.units.held[pico.unit_id] = replace(pico, retired=True)

        await world.remove_flash(BENCH, flash.id)

        assert world.work.flashes.saved == {}
        assert world.units.locks == []
        assert world.work.commits == 1

    async def test_a_flash_not_in_the_workspace_is_not_found(self) -> None:
        # Requirement 3.3: another bench's id reads the same, the fakes holding one bench.
        world = World()
        release = world.hold_version(pico_blink(world), "1.0.0", released=True)
        world.hold_flash(world.units.hold(), release)
        before = world.snapshot()

        with pytest.raises(FlashNotFoundError, match="that flash doesn't exist"):
            await world.remove_flash(BENCH, FlashId(uuid7()))

        assert world.snapshot() == before
        assert world.work.commits == 0
