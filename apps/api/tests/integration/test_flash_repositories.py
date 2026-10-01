"""The flash log's repository against a real PostgreSQL (15-flash-log).

What only the database can answer: the composite key refusing a flash under another workspace's
version, and its RESTRICT refusing to delete a version a flash names, or the firmware above it
(decision 6); a unit's log in the domain's order, ties included (decision 4); `DISTINCT ON`
keeping each unit's newest flash only when it is the firmware's (decision 11); the lists that
keep a version and a firmware; and each read in one statement (requirement 9.3).
"""

from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid7

import pytest
from pydantic import SecretStr
from sqlalchemy import TextClause, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from support.sql import counting
from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.settings import Environment, Settings
from wiredex.firmware.application.ports import FlashEntry
from wiredex.firmware.domain.firmware import Firmware
from wiredex.firmware.domain.flash import Flash, FlashLog, FlashNotes, UnitCode
from wiredex.firmware.domain.semver import SemVer
from wiredex.firmware.domain.values import (
    BoardTarget,
    Changelog,
    FirmwareId,
    FirmwareName,
    FlashId,
    Framework,
    RevisionId,
    UnitId,
    VersionId,
    WorkspaceId,
)
from wiredex.firmware.domain.version import FirmwareVersion, VersionStatus
from wiredex.firmware.infrastructure.unit_of_work import SqlFirmwareUnitOfWork

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

NOW = datetime(2026, 9, 30, 3, tzinfo=UTC)
BENCH = WorkspaceId(uuid7())
OTHER = WorkspaceId(uuid7())
KEY = "fk_flashes_workspace_id_firmware_versions"


@pytest.fixture
async def engine(migrated_database_url: str) -> AsyncIterator[AsyncEngine]:
    settings = Settings(environment=Environment.TEST, database_url=SecretStr(migrated_database_url))
    engine = create_engine(settings)
    yield engine
    async with engine.begin() as connection:
        await connection.execute(
            text("TRUNCATE flashes, source_files, firmware_versions, firmware_revisions, firmware")
        )
    await engine.dispose()


def firmware_work(engine: AsyncEngine, workspace_id: WorkspaceId = BENCH) -> SqlFirmwareUnitOfWork:
    return SqlFirmwareUnitOfWork(create_session_factory(engine), workspace_id)


def a_firmware(name: str = "Weather station", *, workspace_id: WorkspaceId = BENCH) -> Firmware:
    return Firmware(
        id=FirmwareId(uuid7()),
        workspace_id=workspace_id,
        name=FirmwareName(name),
        target=BoardTarget("esp32:esp32:esp32"),
        framework=Framework.ARDUINO,
        description=None,
        created_at=NOW,
        updated_at=NOW,
    )


def a_release(firmware: Firmware, number: str) -> FirmwareVersion:
    return FirmwareVersion(
        id=VersionId(uuid7()),
        workspace_id=firmware.workspace_id,
        firmware_id=firmware.id,
        number=SemVer.parse(number),
        changelog=Changelog(f"What {number} changed."),
        status=VersionStatus.RELEASED,
        based_on=None,
        created_at=NOW,
        updated_at=NOW,
        released_at=NOW,
    )


class Board:
    """A unit as a flash names it: a bare id and the code it was minted with."""

    def __init__(self, code: str) -> None:
        self.id = UnitId(uuid7())
        self.code = UnitCode(code)


def a_flash(
    board: Board, version: FirmwareVersion, *, flashed: int = 0, logged: int | None = None
) -> Flash:
    """The version flashed onto the board `flashed` minutes after NOW, and logged `logged`
    minutes after it, the same minute when not given; no notes, and no revision held it."""
    return Flash(
        id=FlashId(uuid7()),
        workspace_id=version.workspace_id,
        unit_id=board.id,
        unit_code=board.code,
        version_id=version.id,
        revision_id=None,
        flashed_at=NOW + timedelta(minutes=flashed),
        notes=None,
        created_at=NOW + timedelta(minutes=flashed if logged is None else logged),
    )


async def store(engine: AsyncEngine, firmware: Firmware, *versions: FirmwareVersion) -> None:
    async with firmware_work(engine, firmware.workspace_id) as work:
        await work.firmwares.add(firmware)
        for version in versions:
            await work.versions.add(version)
        await work.commit()


async def log(engine: AsyncEngine, *flashes: Flash) -> None:
    async with firmware_work(engine) as work:
        for flash in flashes:
            await work.flashes.add(flash)
        await work.commit()


async def refused(engine: AsyncEngine, statement: TextClause, **values: object) -> None:
    """The statement, as the owner (no row-level security), refused by the flashes' key."""
    with pytest.raises(IntegrityError, match=KEY):
        async with engine.begin() as connection:
            await connection.execute(statement, values)


async def count(engine: AsyncEngine, table: str) -> int:
    async with engine.connect() as connection:
        found = await connection.scalar(text(f"SELECT count(*) FROM {table}"))  # noqa: S608
        return int(found or 0)


def flashes_of(entries: list[FlashEntry]) -> list[Flash]:
    return [entry.flash for entry in entries]


# --- Writing, reading back, removing ---------------------------------------------------------


async def test_a_flash_reads_back_as_written_and_is_removed_alone(engine: AsyncEngine) -> None:
    # Requirements 1.1, 1.7 and 1.8: the code, the recorded revision and the notes kept, to the
    # microsecond; an entry carries its firmware's id and name and its version's number.
    firmware = a_firmware()
    release = a_release(firmware, "1.0.0-RC.1")
    await store(engine, firmware, release)
    esp32 = Board("WX-U-0001")
    noted = replace(
        a_flash(esp32, release),
        revision_id=RevisionId(uuid7()),
        flashed_at=NOW + timedelta(microseconds=7),
        notes=FlashNotes("Bench test at 3.3 V ± 5 %"),
    )
    bare = a_flash(esp32, release, flashed=-60)
    await log(engine, noted, bare)

    async with firmware_work(engine) as work:
        assert await work.flashes.get(noted.id) == noted
        assert await work.flashes.get(bare.id) == bare
        assert await work.flashes.get(FlashId(uuid7())) is None
        entries = await work.flashes.of_unit(esp32.id)
        await work.flashes.remove(noted)
        await work.commit()

    assert entries == [
        FlashEntry(noted, firmware.id, firmware.name, SemVer.parse("1.0.0-rc.1")),
        FlashEntry(bare, firmware.id, firmware.name, SemVer.parse("1.0.0-rc.1")),
    ]
    async with firmware_work(engine) as work:
        assert flashes_of(await work.flashes.of_unit(esp32.id)) == [bare]


async def test_a_flash_under_another_benchs_version_is_refused_by_its_key(
    engine: AsyncEngine,
) -> None:
    """Requirement 6.3, as the owner, whom row-level security doesn't narrow: my workspace on
    the flash, their version as the one flashed. The pair matches nothing of mine."""
    theirs = a_firmware(workspace_id=OTHER)
    their_release = a_release(theirs, "1.0.0")
    await store(engine, theirs, their_release)

    async with firmware_work(engine) as work:
        with pytest.raises(IntegrityError, match=KEY):
            await work.flashes.add(
                replace(a_flash(Board("WX-U-0001"), their_release), workspace_id=BENCH)
            )
    assert await count(engine, "flashes") == 0


async def test_a_flashed_version_and_its_firmware_are_kept_by_the_database(
    engine: AsyncEngine,
) -> None:
    # Decision 6, requirements 5.1 and 5.2: RESTRICT refuses the version, and the firmware whose
    # cascade would reach it, even with no use case asking first. An unflashed version goes.
    firmware = a_firmware()
    flashed, unflashed = a_release(firmware, "1.0.0"), a_release(firmware, "1.1.0")
    await store(engine, firmware, flashed, unflashed)
    flash = a_flash(Board("WX-U-0001"), flashed)
    await log(engine, flash)
    deleting = {
        "version": text("DELETE FROM firmware_versions WHERE id = :id"),
        "firmware": text("DELETE FROM firmware WHERE id = :id"),
    }

    await refused(engine, deleting["version"], id=flashed.id)
    await refused(engine, deleting["firmware"], id=firmware.id)
    async with firmware_work(engine) as work:
        found = await work.versions.get(unflashed.id)
        assert found is not None
        await work.versions.remove(found)
        await work.commit()
    assert await count(engine, "firmware_versions") == 1

    # Once the entry is removed, nothing keeps them.
    async with firmware_work(engine) as work:
        await work.flashes.remove(flash)
        found_firmware = await work.firmwares.locked(firmware.id)
        assert found_firmware is not None
        await work.firmwares.remove(found_firmware)
        await work.commit()
    assert await count(engine, "firmware_versions") == 0


async def test_clear_takes_the_flashes_before_the_versions_they_keep(engine: AsyncEngine) -> None:
    # A demo reset: the RESTRICT would refuse the versions if the flashes stood. Another bench's
    # firmware and flash stay.
    mine, theirs = a_firmware(), a_firmware(workspace_id=OTHER)
    my_release, their_release = a_release(mine, "1.0.0"), a_release(theirs, "1.0.0")
    await store(engine, mine, my_release)
    await store(engine, theirs, their_release)
    await log(engine, a_flash(Board("WX-U-0001"), my_release))
    async with firmware_work(engine, OTHER) as work:
        await work.flashes.add(a_flash(Board("WX-U-0001"), their_release))
        await work.commit()

    async with firmware_work(engine) as work:
        await work.clear()
        await work.commit()

    for table in ("flashes", "firmware_versions", "firmware"):
        assert await count(engine, table) == 1, table


# --- A unit's log ----------------------------------------------------------------------------


async def test_a_units_flashes_come_newest_first_with_ties_ordered(engine: AsyncEngine) -> None:
    # Decision 4: by when it was flashed, then logged, then id; the same order the domain's
    # FlashLog sorts by, in one statement, and another unit's flashes left out.
    firmware = a_firmware()
    first, second = a_release(firmware, "1.0.0"), a_release(firmware, "1.1.0")
    await store(engine, firmware, first, second)
    board, other = Board("WX-U-0001"), Board("WX-U-0002")
    flashes = [
        a_flash(board, first, flashed=0),
        # Flashed last, though logged before the two below.
        a_flash(board, second, flashed=30, logged=30),
        # Flashed at the same minute, logged later: comes first.
        a_flash(board, first, flashed=30, logged=45),
        # Same minute and same logging: the newer id first.
        a_flash(board, second, flashed=30, logged=45),
        # Logged last, backdated to before everything: last in the log.
        a_flash(board, second, flashed=-60, logged=90),
        a_flash(other, second, flashed=120),
    ]
    await log(engine, *flashes)

    async with firmware_work(engine) as work:
        with counting(engine) as statements:
            entries = await work.flashes.of_unit(board.id)
        assert await work.flashes.of_unit(UnitId(uuid7())) == []

    newest_first = flashes_of(entries)
    assert newest_first == list(FlashLog.of(flashes[:5]).items)
    # The pair tied on both times comes newer id first, ahead of the one logged before them.
    tied = sorted(flashes[2:4], key=lambda flash: flash.id, reverse=True)
    assert newest_first == [*tied, flashes[1], flashes[0], flashes[4]]
    assert {entry.flash.version_id: str(entry.number) for entry in entries} == {
        first.id: "1.0.0",
        second.id: "1.1.0",
    }
    assert len(statements) == 1, statements


# --- A firmware's boards ---------------------------------------------------------------------


async def test_each_units_newest_flash_is_kept_only_when_it_is_the_firmwares(
    engine: AsyncEngine,
) -> None:
    # Decision 11: the unit's newest flash by flash time, then logging, decides; an older flash
    # of the firmware doesn't put the unit on its boards. By code, in one statement.
    station, blink, idle = a_firmware("Weather station"), a_firmware("Blink"), a_firmware("Idle")
    old, new = a_release(station, "1.0.0"), a_release(station, "1.1.0")
    blinky = a_release(blink, "0.1.0")
    await store(engine, station, old, new)
    await store(engine, blink, blinky)
    await store(engine, idle, a_release(idle, "1.0.0"))
    upgraded, moved_on, came_back = Board("WX-U-0003"), Board("WX-U-0004"), Board("WX-U-0001")
    backdated, same_minute = Board("WX-U-0002"), Board("WX-U-0005")
    await log(
        engine,
        a_flash(upgraded, old, flashed=0),
        a_flash(upgraded, new, flashed=10),
        a_flash(moved_on, old, flashed=0),
        a_flash(moved_on, blinky, flashed=10),
        a_flash(came_back, blinky, flashed=0),
        a_flash(came_back, old, flashed=10),
        # Logged after the station's 1.1.0 but dated before it: 1.1.0 still runs.
        a_flash(backdated, new, flashed=50, logged=50),
        a_flash(backdated, blinky, flashed=5, logged=60),
        # One minute, two flashes: the later logged runs.
        a_flash(same_minute, old, flashed=20, logged=20),
        a_flash(same_minute, blinky, flashed=20, logged=21),
    )

    async with firmware_work(engine) as work:
        with counting(engine) as statements:
            on_station = await work.flashes.current_on(station.id)
        on_blink = await work.flashes.current_on(blink.id)
        assert await work.flashes.current_on(idle.id) == []
        assert await work.flashes.current_on(FirmwareId(uuid7())) == []

    assert [(str(entry.flash.unit_code), str(entry.number)) for entry in on_station] == [
        ("WX-U-0001", "1.0.0"),
        ("WX-U-0002", "1.1.0"),
        ("WX-U-0003", "1.1.0"),
    ]
    assert {(entry.firmware_id, entry.firmware_name) for entry in on_station} == {
        (station.id, station.name)
    }
    assert [(str(entry.flash.unit_code), str(entry.number)) for entry in on_blink] == [
        ("WX-U-0004", "0.1.0"),
        ("WX-U-0005", "0.1.0"),
    ]
    assert len(statements) == 1, statements


# --- What keeps a version and a firmware -----------------------------------------------------


async def test_of_version_and_of_firmware_list_the_flashes_that_keep_them(
    engine: AsyncEngine,
) -> None:
    # Decision 6: every flash naming the version, or any of the firmware's versions, current or
    # not, by the unit's code and then newest first, each in one statement.
    station, blink = a_firmware("Weather station"), a_firmware("Blink")
    old, new, unflashed = (a_release(station, number) for number in ("1.0.0", "1.1.0", "1.2.0"))
    blinky = a_release(blink, "0.1.0")
    await store(engine, station, old, new, unflashed)
    await store(engine, blink, blinky)
    first, second, elsewhere = Board("WX-U-0001"), Board("WX-U-0002"), Board("WX-U-0003")
    second_old = a_flash(second, old, flashed=5)
    first_old = a_flash(first, old, flashed=10)
    first_older = a_flash(first, old, flashed=-10)
    first_new = a_flash(first, new, flashed=20)
    await log(engine, second_old, first_old, first_older, first_new, a_flash(elsewhere, blinky))

    async with firmware_work(engine) as work:
        with counting(engine) as by_version:
            keeping_old = await work.flashes.of_version(old.id)
        with counting(engine) as by_firmware:
            keeping_station = await work.flashes.of_firmware(station.id)
        keeping_new = await work.flashes.of_version(new.id)
        assert await work.flashes.of_version(unflashed.id) == []
        assert await work.flashes.of_firmware(FirmwareId(uuid7())) == []

    assert flashes_of(keeping_old) == [first_old, first_older, second_old]
    assert flashes_of(keeping_station) == [first_new, first_old, first_older, second_old]
    assert flashes_of(keeping_new) == [first_new]
    assert [str(entry.number) for entry in keeping_station] == ["1.1.0", "1.0.0", "1.0.0", "1.0.0"]
    assert {(entry.firmware_id, entry.firmware_name) for entry in keeping_station} == {
        (station.id, station.name)
    }
    assert len(by_version) == 1, by_version
    assert len(by_firmware) == 1, by_firmware
