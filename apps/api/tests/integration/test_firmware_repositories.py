"""The firmware repositories and unit of work against a real PostgreSQL (13-firmware-versions).

What only the database can answer: the composite keys refusing a row filed under another
workspace's firmware or version; the cascades and `based_on`'s SET NULL; the unique indexes on
folded names and paths, and on numbers; the CHECKs; the escaped `ILIKE` and the orders the fakes
promise; a version's files read back exactly as written, from one insert; the aggregate summing
their stored sizes; a fork's copy in two statements; and the firmware's row lock serializing
writes to it (decision 8).
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import astuple, replace
from datetime import UTC, datetime, timedelta
from uuid import uuid7

import pytest
from pydantic import SecretStr
from sqlalchemy import TextClause, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from support.identity import ManualClock, NewIds
from support.sql import counting
from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.settings import Environment, Settings
from wiredex.firmware.application.firmware import UnitOfWorkFactory
from wiredex.firmware.application.links import CopyRevisionLinks
from wiredex.firmware.application.ports import NewSourceFile
from wiredex.firmware.application.sources import AddSourceFiles
from wiredex.firmware.application.versions import ReleaseVersion, StartVersion
from wiredex.firmware.domain.errors import VersionReleasedError
from wiredex.firmware.domain.firmware import Firmware
from wiredex.firmware.domain.semver import SemVer
from wiredex.firmware.domain.source import SourceFile, SourceFiles, SourcePath, SourceText
from wiredex.firmware.domain.values import (
    BoardTarget,
    Changelog,
    Description,
    FirmwareId,
    FirmwareName,
    Framework,
    RevisionId,
    SourceFileId,
    VersionId,
    WorkspaceId,
)
from wiredex.firmware.domain.version import FirmwareVersion, VersionStatus
from wiredex.firmware.infrastructure.unit_of_work import (
    SqlFirmwareRepositories,
    SqlFirmwareUnitOfWork,
)

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

NOW = datetime(2026, 9, 30, 3, tzinfo=UTC)
BENCH = WorkspaceId(uuid7())
OTHER = WorkspaceId(uuid7())


@pytest.fixture
async def engine(migrated_database_url: str) -> AsyncIterator[AsyncEngine]:
    settings = Settings(environment=Environment.TEST, database_url=SecretStr(migrated_database_url))
    engine = create_engine(settings)
    yield engine
    async with engine.begin() as connection:
        # No CASCADE, so every table that keys into these is named, `flashes` among them.
        await connection.execute(
            text("TRUNCATE flashes, source_files, firmware_versions, firmware_revisions, firmware")
        )
    await engine.dispose()


def firmware_work(engine: AsyncEngine, workspace_id: WorkspaceId = BENCH) -> SqlFirmwareUnitOfWork:
    return SqlFirmwareUnitOfWork(create_session_factory(engine), workspace_id)


def factory(engine: AsyncEngine) -> UnitOfWorkFactory:
    """What bootstrap will hand the use cases: one unit of work per call, for a workspace."""
    sessions = create_session_factory(engine)
    return lambda workspace_id: SqlFirmwareUnitOfWork(sessions, workspace_id)


def a_firmware(
    name: str = "Weather station",
    *,
    target: str = "esp32:esp32:esp32",
    minutes: int = 0,
    workspace_id: WorkspaceId = BENCH,
) -> Firmware:
    """A firmware with no description, created and last changed `minutes` after NOW."""
    when = NOW + timedelta(minutes=minutes)
    return Firmware(
        id=FirmwareId(uuid7()),
        workspace_id=workspace_id,
        name=FirmwareName(name),
        target=BoardTarget(target),
        framework=Framework.ARDUINO,
        description=None,
        created_at=when,
        updated_at=when,
    )


def a_version(
    firmware: Firmware,
    number: str,
    *,
    released: bool = False,
    based_on: FirmwareVersion | None = None,
) -> FirmwareVersion:
    """A draft with no changelog, or a release with one, created at NOW."""
    return FirmwareVersion(
        id=VersionId(uuid7()),
        workspace_id=firmware.workspace_id,
        firmware_id=firmware.id,
        number=SemVer.parse(number),
        changelog=Changelog(f"What {number} changed.") if released else None,
        status=VersionStatus.RELEASED if released else VersionStatus.DRAFT,
        based_on=None if based_on is None else based_on.id,
        created_at=NOW,
        updated_at=NOW,
        released_at=NOW if released else None,
    )


def a_file(path: str, text_value: str = "") -> SourceFile:
    return SourceFile(SourceFileId(uuid7()), SourcePath(path), SourceText(text_value))


async def store(engine: AsyncEngine, firmware: Firmware, *versions: FirmwareVersion) -> None:
    """A firmware and its versions, in one transaction of the firmware's workspace."""
    async with firmware_work(engine, firmware.workspace_id) as work:
        await work.firmwares.add(firmware)
        for version in versions:
            await work.versions.add(version)
        await work.commit()


async def store_files(engine: AsyncEngine, version: FirmwareVersion, *files: SourceFile) -> None:
    async with firmware_work(engine, version.workspace_id) as work:
        await work.sources.add_all(version.id, files)
        await work.commit()


async def link(engine: AsyncEngine, firmware: Firmware, *revision_ids: RevisionId) -> None:
    async with firmware_work(engine, firmware.workspace_id) as work:
        for revision_id in revision_ids:
            await work.links.add(firmware.id, revision_id, NOW)
        await work.commit()


async def count(engine: AsyncEngine, table: str) -> int:
    async with engine.connect() as connection:
        found = await connection.scalar(text(f"SELECT count(*) FROM {table}"))  # noqa: S608
        return int(found or 0)


async def refused(
    engine: AsyncEngine, constraint: str, statement: TextClause, **values: object
) -> None:
    """The statement, as the owner (no row-level security), refused by the named key or CHECK."""
    with pytest.raises(IntegrityError, match=constraint):
        async with engine.begin() as connection:
            await connection.execute(statement, values)


# --- Reading back what was written -----------------------------------------------------------


async def test_a_firmware_and_its_versions_read_back_as_written(engine: AsyncEngine) -> None:
    firmware = a_firmware()
    firmware.framework = Framework.ESP_IDF
    firmware.description = Description("Reads the BME280.\n\nSleeps between readings.")
    base = a_version(firmware, "1.0.0-RC.1", released=True)
    draft = a_version(firmware, "v1.0.0", based_on=base)
    await store(engine, firmware, base, draft)

    async with firmware_work(engine) as work:
        found = await work.firmwares.get(firmware.id)
        found_base = await work.versions.get(base.id)
        found_draft = await work.versions.get(draft.id)
    async with engine.connect() as connection:
        numbers = await connection.scalars(text("SELECT version FROM firmware_versions"))
        stored = sorted(numbers)

    assert found is not None
    assert astuple(found) == astuple(firmware)
    assert found_base is not None
    assert astuple(found_base) == astuple(base)
    assert found_draft is not None
    assert astuple(found_draft) == astuple(draft)
    # Each number is stored as its canonical text, lower-cased and without its `v`.
    assert stored == ["1.0.0", "1.0.0-rc.1"]


async def test_firmware_of_reads_one_column_and_leaves_the_session_empty(
    engine: AsyncEngine,
) -> None:
    # Decision 8: the version enters the session only once its firmware is locked.
    firmware = a_firmware()
    version = a_version(firmware, "1.0.0")
    await store(engine, firmware, version)

    async with firmware_work(engine) as work:
        assert await work.versions.firmware_of(version.id) == firmware.id
        assert await work.versions.firmware_of(VersionId(uuid7())) is None
        assert list(work.session.identity_map.values()) == []


async def test_the_lock_and_the_reads_under_it_refresh_what_the_session_held(
    engine: AsyncEngine,
) -> None:
    # A copy read before the lock is refreshed with the row as another transaction left it,
    # rather than handed back stale (decision 8).
    firmware = a_firmware()
    version = a_version(firmware, "1.0.0")
    await store(engine, firmware, version)

    async with firmware_work(engine) as work:
        held = await work.firmwares.get(firmware.id)
        held_version = await work.versions.get(version.id)
        async with engine.begin() as other:
            await other.execute(
                text("UPDATE firmware SET name = 'Renamed' WHERE id = :id"), {"id": firmware.id}
            )
            await other.execute(
                text(
                    "UPDATE firmware_versions SET status = 'released', released_at = now(),"
                    " changelog = 'Released meanwhile.' WHERE id = :id"
                ),
                {"id": version.id},
            )
        locked = await work.firmwares.locked(firmware.id)
        versions = await work.versions.of_firmware(firmware.id)
        again = await work.versions.get(version.id)

    assert locked is held
    assert held is not None
    assert held.name == FirmwareName("Renamed")
    assert versions.items == (held_version,)
    assert again is held_version
    assert held_version is not None
    assert held_version.status is VersionStatus.RELEASED


# --- Names and the search --------------------------------------------------------------------


async def test_a_name_is_found_and_held_folded(engine: AsyncEngine) -> None:
    # `named` and `uq_firmware_name` fold with the same `lower(name)` (requirement 1.3).
    station = a_firmware("Weather station")
    await store(engine, station)

    async with firmware_work(engine) as work:
        found = await work.firmwares.named(FirmwareName("WEATHER  station"))
        assert found is not None
        assert found.id == station.id
        assert await work.firmwares.named(FirmwareName("Weather")) is None

    async with firmware_work(engine) as work:
        # `add` flushes, so the index refuses the row there and then.
        with pytest.raises(IntegrityError, match="uq_firmware_name"):
            await work.firmwares.add(a_firmware("weather STATION"))

    # Unique per workspace: another bench may use the name.
    await store(engine, a_firmware("Weather station", workspace_id=OTHER))


async def test_the_search_matches_wildcards_as_themselves_and_opens_on_the_last_change(
    engine: AsyncEngine,
) -> None:
    # Requirements 2.2 and 2.3, agreeing with the fake: `in` over the name and the target,
    # lower-cased, last change first, a tie by the newer id first.
    held = [
        a_firmware("100% humidity", minutes=1),
        a_firmware("1000 humidity", minutes=2),
        a_firmware("a_b sensor", target="RPI_PICO", minutes=3),
        a_firmware("axb sensor", minutes=4),
        a_firmware("Weather station", minutes=4),
    ]
    for firmware in held:
        await store(engine, firmware)
    await store(engine, a_firmware("Weather station", workspace_id=OTHER))

    wanted = ("100%", "a_b", "%", "_", "WEATHER", "pico", "ESP32:", "humid", "nowhere", "")
    async with firmware_work(engine) as work:
        found = {text_value: await work.firmwares.matching(text_value) for text_value in wanted}

    newest_first = sorted(held, key=lambda one: (one.updated_at, one.id), reverse=True)
    for text_value, firmware_found in found.items():
        folded = text_value.lower()
        expected = [
            one.id
            for one in newest_first
            if folded in one.name.value.lower() or folded in one.target.value.lower()
        ]
        assert [one.id for one in firmware_found] == expected, text_value
    assert [one.name.value for one in found["%"]] == ["100% humidity"]
    assert [one.name.value for one in found["_"]] == ["a_b sensor"]
    assert [one.name.value for one in found[""]][:2] == ["Weather station", "axb sensor"]


# --- Links -----------------------------------------------------------------------------------


async def test_a_link_is_written_once_and_read_in_link_order(engine: AsyncEngine) -> None:
    # Requirements 3.1, 3.2 and 3.5: `add` and `remove` say whether they changed a row, and a
    # repeated link keeps its date.
    firmware = a_firmware()
    await store(engine, firmware)
    first, second, third = (RevisionId(uuid7()) for _ in range(3))

    async with firmware_work(engine) as work:
        assert await work.links.add(firmware.id, second, NOW + timedelta(minutes=1))
        assert await work.links.add(firmware.id, first, NOW)
        assert await work.links.add(firmware.id, third, NOW + timedelta(minutes=1))
        assert not await work.links.add(firmware.id, first, NOW + timedelta(hours=1))
        await work.commit()
    async with firmware_work(engine) as work:
        # Two linked at one instant come by the revision's id.
        assert await work.links.of_firmware(firmware.id) == (first, *sorted([second, third]))
        assert await work.links.remove(firmware.id, second)
        assert not await work.links.remove(firmware.id, second)
        await work.commit()
    async with firmware_work(engine) as work:
        assert await work.links.of_firmware(firmware.id) == (first, third)


async def test_running_on_joins_the_linked_firmware_in_one_read_by_folded_name(
    engine: AsyncEngine,
) -> None:
    # Requirement 3.4: case-sensitive text would put Gamma before beta.
    gamma, beta, alpha, unlinked = (a_firmware(name) for name in ("Gamma", "beta", "Alpha", "D"))
    for firmware in (gamma, beta, alpha, unlinked):
        await store(engine, firmware)
    revision, elsewhere = RevisionId(uuid7()), RevisionId(uuid7())
    for firmware in (gamma, beta, alpha):
        await link(engine, firmware, revision)
    await link(engine, unlinked, elsewhere)

    async with firmware_work(engine) as work:
        with counting(engine) as statements:
            found = await work.firmwares.running_on(revision)

    assert [one.id for one in found] == [alpha.id, beta.id, gamma.id]
    assert len(statements) == 1, statements


async def test_a_forks_copy_links_the_target_and_moves_those_firmware_in_two_statements(
    engine: AsyncEngine,
) -> None:
    # Decision 4, over the repositories a fork's session binds: the source's links given to the
    # target, dated when it was forked, and nothing else changed.
    station, logger, blink = (a_firmware(name) for name in ("Weather station", "Logger", "Blink"))
    for firmware in (station, logger, blink):
        await store(engine, firmware)
    source, target, elsewhere = (RevisionId(uuid7()) for _ in range(3))
    await link(engine, station, source)
    await link(engine, logger, source)
    await link(engine, blink, elsewhere)
    forked_at = NOW + timedelta(hours=1)

    async with firmware_work(engine) as work:
        copy = CopyRevisionLinks(SqlFirmwareRepositories(work.session, BENCH))
        with counting(engine) as statements:
            await copy.copy(source, target, forked_at)
        await work.commit()

    async with firmware_work(engine) as work:
        on_target = {one.id for one in await work.firmwares.running_on(target)}
        on_source = {one.id for one in await work.firmwares.running_on(source)}
        on_elsewhere = [one.id for one in await work.firmwares.running_on(elsewhere)]
        changed = {one.id: one.updated_at for one in await work.firmwares.matching("")}
    async with engine.connect() as connection:
        dated = await connection.scalars(
            text("SELECT DISTINCT created_at FROM firmware_revisions WHERE revision_id = :id"),
            {"id": target},
        )
        dates = list(dated)
    assert len(statements) == 2, statements
    assert on_target == on_source == {station.id, logger.id}
    assert on_elsewhere == [blink.id]
    assert changed == {station.id: forked_at, logger.id: forked_at, blink.id: NOW}
    assert dates == [forked_at]


# --- Source files ----------------------------------------------------------------------------


async def test_a_versions_files_read_back_exactly_from_one_insert(engine: AsyncEngine) -> None:
    # Requirements 7.4 and 7.10: tabs, trailing spaces, a missing final line break and
    # multi-byte characters kept; CRLF read as LF; `.ino` first, then by folded path.
    firmware = a_firmware()
    version = a_version(firmware, "1.0.0")
    await store(engine, firmware, version)
    files = [
        a_file("src/sensor.cpp", '#include "sensor.h"\n\tint read() {  \n\treturn 21;\n}'),
        a_file("weather_station.ino", "void setup() {}\r\nvoid loop() {}\r\n"),
        a_file("lib/BME280/bme280.h", "// °C, µs, ≥ and 🌡\n"),
        a_file("empty.txt"),
        a_file("Config.h", "#define SDA 21\n#define SCL 22\n"),
    ]

    async with firmware_work(engine) as work:
        with counting(engine) as written:
            await work.sources.add_all(version.id, files)
        with counting(engine) as nothing:
            await work.sources.add_all(version.id, [])
        await work.commit()
    async with firmware_work(engine) as work:
        with counting(engine) as read:
            back = await work.sources.of_version(version.id)
    async with engine.connect() as connection:
        rows = await connection.execute(text("SELECT path, size FROM source_files"))
        sizes = dict(rows.tuples().all())

    assert back == SourceFiles.of(files)
    assert [file.path.value for file in back.items] == [
        "weather_station.ino",
        "Config.h",
        "empty.txt",
        "lib/BME280/bme280.h",
        "src/sensor.cpp",
    ]
    assert back.items[0].text.value == "void setup() {}\nvoid loop() {}\n"
    assert len(written) == 1, written
    assert nothing == []
    assert len(read) == 1, read
    # The stored sizes are the texts' bytes of UTF-8, which the CHECK holds them to.
    assert sizes == {file.path.value: file.text.size for file in files}
    assert sizes["lib/BME280/bme280.h"] == len("// °C, µs, ≥ and 🌡\n".encode())


async def test_a_file_is_edited_and_removed_under_its_own_version_only(engine: AsyncEngine) -> None:
    firmware = a_firmware()
    first, second = a_version(firmware, "1.0.0"), a_version(firmware, "1.1.0")
    await store(engine, firmware, first, second)
    sketch = a_file("sketch.ino", "void loop() {}\n")
    await store_files(engine, first, sketch)
    await store_files(engine, second, a_file("sketch.ino", "void loop() {}\n"))
    renamed = SourceFile(sketch.id, SourcePath("weather_station.ino"), SourceText("// read()\n"))

    async with firmware_work(engine) as work:
        await work.sources.update(first.id, sketch, renamed)
        # Named under the other version, the file isn't found there: nothing is removed.
        await work.sources.remove(second.id, renamed)
        await work.commit()
    async with firmware_work(engine) as work:
        assert (await work.sources.of_version(first.id)).items == (renamed,)
        assert len((await work.sources.of_version(second.id)).items) == 1
        await work.sources.remove(first.id, renamed)
        await work.commit()

    async with firmware_work(engine) as work:
        assert (await work.sources.of_version(first.id)).items == ()
    assert await count(engine, "source_files") == 1


async def test_summaries_count_and_size_the_files_in_one_aggregate_highest_first(
    engine: AsyncEngine,
) -> None:
    # Decisions 9 and 12: the stored sizes summed, and SemVer's order, which as text would put
    # 1.10.0 before 1.2.0 the wrong way round.
    station, blink, bare = (a_firmware(name) for name in ("Weather station", "Blink", "Bare"))
    older = a_version(station, "1.2.0", released=True)
    newest = a_version(station, "1.10.0")
    candidate = a_version(station, "1.10.0-rc.1", released=True)
    await store(engine, station, older, newest, candidate)
    await store(engine, blink, a_version(blink, "0.1.0"))
    await store(engine, bare)
    await store_files(engine, older, a_file("a.ino", "abc"), a_file("b.h", "ü"))
    await store_files(engine, candidate, a_file("a.ino", "12345"))

    async with firmware_work(engine) as work:
        with counting(engine) as statements:
            summaries = await work.versions.summaries([station.id, blink.id, bare.id])
        with counting(engine) as nothing:
            assert await work.versions.summaries([]) == {}
        ordered = await work.versions.of_firmware(station.id)

    def rows(firmware: Firmware) -> list[tuple[str, int, int]]:
        return [
            (str(summary.version.number), summary.files, summary.size)
            for summary in summaries[firmware.id]
        ]

    assert rows(station) == [("1.10.0", 0, 0), ("1.10.0-rc.1", 1, 5), ("1.2.0", 2, 5)]
    assert rows(blink) == [("0.1.0", 0, 0)]
    assert bare.id not in summaries
    assert [str(version.number) for version in ordered.items] == ["1.10.0", "1.10.0-rc.1", "1.2.0"]
    assert len(statements) == 1, statements
    assert nothing == []


# --- What the keys and the CHECKs do ----------------------------------------------------------


async def test_deleting_a_firmware_takes_its_versions_files_and_links(engine: AsyncEngine) -> None:
    # Requirement 1.9, by the composite keys' ON DELETE CASCADE.
    station, kept = a_firmware("Weather station"), a_firmware("Blink")
    release = a_version(station, "1.0.0", released=True)
    draft = a_version(station, "1.1.0", based_on=release)
    kept_version = a_version(kept, "1.0.0")
    await store(engine, station, release, draft)
    await store(engine, kept, kept_version)
    for version in (release, draft, kept_version):
        await store_files(engine, version, a_file("main.ino"))
    revision = RevisionId(uuid7())
    await link(engine, station, revision)
    await link(engine, kept, revision)

    async with firmware_work(engine) as work:
        found = await work.firmwares.locked(station.id)
        assert found is not None
        await work.firmwares.remove(found)
        await work.commit()

    async with firmware_work(engine) as work:
        assert await work.firmwares.get(station.id) is None
        assert (await work.versions.of_firmware(station.id)).items == ()
        assert await work.links.of_firmware(station.id) == ()
        assert [one.id for one in await work.firmwares.running_on(revision)] == [kept.id]
        assert len((await work.sources.of_version(kept_version.id)).items) == 1
    assert await count(engine, "firmware_versions") == 1
    assert await count(engine, "source_files") == 1


async def test_deleting_a_base_keeps_the_versions_started_from_it(engine: AsyncEngine) -> None:
    # Requirements 8.1 and 8.2: the base's files go by the cascade, and `based_on` is cleared
    # by ON DELETE SET NULL.
    firmware = a_firmware()
    base = a_version(firmware, "1.0.0", released=True)
    draft = a_version(firmware, "1.1.0", based_on=base)
    await store(engine, firmware, base, draft)
    await store_files(engine, base, a_file("sketch.ino", "1.0.0"))
    await store_files(engine, draft, a_file("sketch.ino", "1.1.0"))

    async with firmware_work(engine) as work:
        found = await work.versions.get(base.id)
        assert found is not None
        await work.versions.remove(found)
        await work.commit()

    async with firmware_work(engine) as work:
        assert await work.versions.get(base.id) is None
        kept = await work.versions.get(draft.id)
        files = await work.sources.of_version(draft.id)
    assert kept is not None
    assert kept.based_on is None
    assert [file.text.value for file in files.items] == ["1.1.0"]
    assert await count(engine, "source_files") == 1


async def test_numbers_and_paths_are_unique_as_their_indexes_hold_them(
    engine: AsyncEngine,
) -> None:
    # Requirements 5.2 and 7.3: a number once per firmware, a folded path once per version.
    station, blink = a_firmware("Weather station"), a_firmware("Blink")
    version, other = a_version(station, "1.0.0"), a_version(station, "1.1.0")
    await store(engine, station, version, other)
    # Another firmware may use the number.
    await store(engine, blink, a_version(blink, "1.0.0"))

    async with firmware_work(engine) as work:
        with pytest.raises(IntegrityError, match="uq_firmware_versions_version"):
            await work.versions.add(a_version(station, "v1.0.0"))
    await store_files(engine, version, a_file("Config.h"))
    with pytest.raises(IntegrityError, match="uq_source_files_path"):
        await store_files(engine, version, a_file("config.H"))
    # Another version may hold the path.
    await store_files(engine, other, a_file("config.h"))


async def test_the_database_refuses_what_the_domain_never_writes(engine: AsyncEngine) -> None:
    firmware = a_firmware()
    version = a_version(firmware, "1.0.0")
    await store(engine, firmware, version)
    file_row = text(
        "INSERT INTO source_files (id, workspace_id, version_id, path, content, size)"
        " VALUES (:id, :workspace, :version, 'a.ino', 'ü', :size)"
    )
    mine = {"workspace": BENCH, "version": version.id}

    # ü is two bytes of UTF-8: a size of one is not its length.
    await refused(engine, "ck_source_files_size_is_length", file_row, id=uuid7(), size=1, **mine)
    for change in ("status = 'released'", "released_at = now()"):
        await refused(
            engine,
            "ck_firmware_versions_released_dated",
            text(f"UPDATE firmware_versions SET {change} WHERE id = :id"),  # noqa: S608
            id=version.id,
        )
    await refused(
        engine,
        "ck_firmware_versions_status",
        text("UPDATE firmware_versions SET status = 'archived' WHERE id = :id"),
        id=version.id,
    )
    await refused(
        engine,
        "ck_firmware_framework",
        text("UPDATE firmware SET framework = 'zephyr' WHERE id = :id"),
        id=firmware.id,
    )


async def test_rows_under_another_workspaces_firmware_or_version_are_refused_by_their_keys(
    engine: AsyncEngine,
) -> None:
    """Requirement 9.4: the composite keys, which no policy is needed for.

    As the owner, whom row-level security doesn't narrow: my workspace on the row, their
    firmware or version as its parent. The pair matches nothing of mine, and the database
    refuses it.
    """
    theirs = a_firmware(workspace_id=OTHER)
    their_version = a_version(theirs, "1.0.0")
    await store(engine, theirs, their_version)

    async with firmware_work(engine) as work:
        with pytest.raises(IntegrityError, match="fk_firmware_versions_workspace_id_firmware"):
            await work.versions.add(replace(a_version(theirs, "2.0.0"), workspace_id=BENCH))
    await refused(
        engine,
        "fk_firmware_revisions_workspace_id_firmware",
        text(
            "INSERT INTO firmware_revisions (workspace_id, firmware_id, revision_id, created_at)"
            " VALUES (:workspace, :firmware, :revision, now())"
        ),
        workspace=BENCH,
        firmware=theirs.id,
        revision=uuid7(),
    )
    await refused(
        engine,
        "fk_source_files_workspace_id_firmware_versions",
        text(
            "INSERT INTO source_files (id, workspace_id, version_id, path, content, size)"
            " VALUES (:id, :workspace, :version, 'a.ino', '', 0)"
        ),
        id=uuid7(),
        workspace=BENCH,
        version=their_version.id,
    )


async def test_clear_empties_only_its_own_workspace(engine: AsyncEngine) -> None:
    mine, theirs = a_firmware(), a_firmware(workspace_id=OTHER)
    release = a_version(mine, "1.0.0", released=True)
    draft = a_version(mine, "1.1.0", based_on=release)
    their_version = a_version(theirs, "1.0.0")
    await store(engine, mine, release, draft)
    await store(engine, theirs, their_version)
    for version in (release, draft, their_version):
        await store_files(engine, version, a_file("main.ino"))
    await link(engine, mine, RevisionId(uuid7()))
    await link(engine, theirs, RevisionId(uuid7()))

    async with firmware_work(engine) as work:
        await work.clear()
        await work.commit()

    async with firmware_work(engine, OTHER) as work:
        assert [one.id for one in await work.firmwares.matching("")] == [theirs.id]
    for table in ("firmware", "firmware_revisions", "firmware_versions", "source_files"):
        assert await count(engine, table) == 1, table


# --- Writes through the use cases, and the firmware's lock -------------------------------------


async def test_a_draft_from_a_release_copies_its_files_and_a_write_moves_both_last_changes(
    engine: AsyncEngine,
) -> None:
    # The version is flushed as it is added, so its copies, inserted with Core, find its row;
    # `touch` changes mapped attributes, which the commit writes (requirement 2.2).
    firmware = a_firmware()
    release = a_version(firmware, "1.0.0", released=True)
    await store(engine, firmware, release)
    await store_files(engine, release, a_file("sketch.ino", "void loop() {}\n"), a_file("x.h"))
    clock = ManualClock(NOW + timedelta(hours=1))
    ids = NewIds()
    work = factory(engine)

    started = await StartVersion(work, clock, ids)(BENCH, firmware.id, base_id=release.id)
    clock.advance(timedelta(minutes=1))
    added = await AddSourceFiles(work, clock, ids)(
        BENCH, started.version.id, [NewSourceFile("lib/bme.h", "#pragma once\n")]
    )

    async with firmware_work(engine) as check:
        draft = await check.versions.get(started.version.id)
        moved = await check.firmwares.get(firmware.id)
        files = await check.sources.of_version(started.version.id)
        copied_from = await check.sources.of_version(release.id)
    assert draft is not None
    assert moved is not None
    assert (str(draft.number), draft.based_on) == ("1.0.1", release.id)
    assert [file.path.value for file in files.items] == ["sketch.ino", "lib/bme.h", "x.h"]
    assert {file.id for file in files.items}.isdisjoint(file.id for file in copied_from.items)
    assert [file.path.value for file in added] == ["lib/bme.h"]
    assert draft.updated_at == moved.updated_at == clock.now()


@asynccontextmanager
async def firmware_held(engine: AsyncEngine, firmware_id: FirmwareId) -> AsyncIterator[None]:
    """The firmware's row locked by an outside transaction until the block ends.

    Left to themselves, two requests started together mostly run one after the other (the
    second is still getting its connection), which would hide a missing lock. Holding the row
    lines them up at `Firmwares.locked` before either reads the version.
    """
    async with engine.begin() as holder:
        await holder.execute(
            text("SELECT id FROM firmware WHERE id = :id FOR UPDATE"), {"id": firmware_id}
        )
        yield


async def until_waiting(engine: AsyncEngine, count: int) -> None:
    """Returns once `count` transactions wait on a lock, or fails: a write that never waits for
    the firmware's row isn't taking turns."""
    for _ in range(200):
        # A transaction each: pg_stat_activity is read once per transaction.
        async with engine.connect() as watcher:
            waiting = await watcher.scalar(
                text("SELECT count(*) FROM pg_stat_activity WHERE wait_event_type = 'Lock'")
            )
        if (waiting or 0) >= count:
            return
        await asyncio.sleep(0.05)
    pytest.fail(f"expected {count} transactions waiting for the firmware's lock")


async def test_a_file_written_behind_a_release_finds_the_version_released(
    engine: AsyncEngine,
) -> None:
    # Requirement 6.7: the release queues for the firmware's lock first and the file write
    # behind it. Once the release commits, the write reads the version fresh and is refused, so
    # the version keeps the files it was released with.
    firmware = a_firmware()
    draft = a_version(firmware, "1.0.0")
    draft.changelog = Changelog("First light.")
    await store(engine, firmware, draft)
    sketch = a_file("sketch.ino", "void setup() {}\n")
    await store_files(engine, draft, sketch)
    clock = ManualClock(NOW + timedelta(hours=1))
    work = factory(engine)
    release = ReleaseVersion(work, clock)
    add = AddSourceFiles(work, clock, NewIds())

    async with firmware_held(engine, firmware.id):
        releasing = asyncio.create_task(release(BENCH, draft.id))
        await until_waiting(engine, 1)
        adding = asyncio.create_task(add(BENCH, draft.id, [NewSourceFile("config.h", "")]))
        await until_waiting(engine, 2)
    released = await releasing
    with pytest.raises(VersionReleasedError):
        await adding

    async with firmware_work(engine) as check:
        stored = await check.sources.of_version(draft.id)
    assert released.version.status is VersionStatus.RELEASED
    assert released.files == stored == SourceFiles.of([sketch])


async def test_two_versions_started_at_once_take_distinct_numbers(engine: AsyncEngine) -> None:
    # Requirement 6.7: each start reads the versions once the other has committed, so the
    # second suggests the number after the first's.
    firmware = a_firmware()
    await store(engine, firmware, a_version(firmware, "1.2.0", released=True))
    start = StartVersion(factory(engine), ManualClock(NOW + timedelta(hours=1)), NewIds())

    async with firmware_held(engine, firmware.id):
        tasks = [asyncio.create_task(start(BENCH, firmware.id)) for _ in range(2)]
        await until_waiting(engine, 2)
    started = await asyncio.gather(*tasks)

    assert sorted(str(view.version.number) for view in started) == ["1.2.1", "1.2.2"]
