"""Workspace isolation over the firmware tables, as the role the API logs in with.

The repositories filter `workspace_id` themselves, but that is a promise the code makes. This
is the gate underneath it (ADR 0007, requirements 9.1 and 9.3): as `wiredex_app`, another
workspace's firmware, links, versions and source files aren't there to be read or written,
filter or no filter.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid7

import pytest
from pydantic import SecretStr
from sqlalchemy import Table, insert, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.settings import Environment, Settings
from wiredex.firmware.domain.firmware import Firmware
from wiredex.firmware.domain.semver import SemVer
from wiredex.firmware.domain.source import SourceFile, SourcePath, SourceText
from wiredex.firmware.domain.values import (
    BoardTarget,
    Changelog,
    FirmwareId,
    FirmwareName,
    Framework,
    RevisionId,
    SourceFileId,
    VersionId,
    WorkspaceId,
)
from wiredex.firmware.domain.version import FirmwareVersion, VersionStatus
from wiredex.firmware.infrastructure.orm import (
    firmware_revisions,
    firmware_table,
    firmware_versions,
    source_files,
)
from wiredex.firmware.infrastructure.unit_of_work import SqlFirmwareUnitOfWork

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

NOW = datetime(2026, 9, 30, 3, tzinfo=UTC)
MINE = WorkspaceId(uuid7())
THEIRS = WorkspaceId(uuid7())
# A revision of projects, by id alone: a link names it with no key, so none has to exist.
BREADBOARD = RevisionId(uuid7())

# The rows of all four tables, counted without a filter: only the policy narrows them.
EVERY_ROW = text(
    "SELECT (SELECT count(*) FROM firmware) + (SELECT count(*) FROM firmware_revisions)"
    " + (SELECT count(*) FROM firmware_versions) + (SELECT count(*) FROM source_files)"
)


@pytest.fixture
async def admin(migrated_database_url: str) -> AsyncIterator[AsyncEngine]:
    """The schema owner, which the policies don't apply to: it sees every workspace."""
    engine = create_async_engine(migrated_database_url)
    yield engine
    await engine.dispose()


@pytest.fixture(autouse=True)
async def clean(admin: AsyncEngine) -> AsyncIterator[None]:
    """Emptied by the owner afterwards: the app role is granted no TRUNCATE."""
    yield
    async with admin.begin() as connection:
        await connection.execute(
            text("TRUNCATE source_files, firmware_versions, firmware_revisions, firmware")
        )


@pytest.fixture
async def app(app_database_url: str) -> AsyncIterator[AsyncEngine]:
    """The API's role, with the API's engine: row security applies."""
    settings = Settings(environment=Environment.TEST, database_url=SecretStr(app_database_url))
    engine = create_engine(settings)
    yield engine
    await engine.dispose()


def firmware_work(engine: AsyncEngine, workspace_id: WorkspaceId) -> SqlFirmwareUnitOfWork:
    return SqlFirmwareUnitOfWork(create_session_factory(engine), workspace_id)


def a_firmware(workspace_id: WorkspaceId) -> Firmware:
    return Firmware(
        id=FirmwareId(uuid7()),
        workspace_id=workspace_id,
        name=FirmwareName("Weather station"),
        target=BoardTarget("esp32:esp32:esp32"),
        framework=Framework.ARDUINO,
        description=None,
        created_at=NOW,
        updated_at=NOW,
    )


def a_release(firmware: Firmware, number: str = "1.0.0") -> FirmwareVersion:
    return FirmwareVersion(
        id=VersionId(uuid7()),
        workspace_id=firmware.workspace_id,
        firmware_id=firmware.id,
        number=SemVer.parse(number),
        changelog=Changelog("Reads the BME280 every five minutes."),
        status=VersionStatus.RELEASED,
        based_on=None,
        created_at=NOW,
        updated_at=NOW,
        released_at=NOW,
    )


async def seed_my_bench(engine: AsyncEngine) -> tuple[Firmware, FirmwareVersion, SourceFile]:
    """One row in each table, all mine: a firmware running on the breadboard, its release and
    the release's sketch."""
    firmware = a_firmware(MINE)
    release = a_release(firmware)
    sketch = SourceFile(
        SourceFileId(uuid7()), SourcePath("weather_station.ino"), SourceText("void setup() {}\n")
    )
    async with firmware_work(engine, MINE) as work:
        await work.firmwares.add(firmware)
        await work.links.add(firmware.id, BREADBOARD, NOW)
        await work.versions.add(release)
        await work.sources.add_all(release.id, [sketch])
        await work.commit()
    return firmware, release, sketch


async def test_my_own_bench_is_readable(app: AsyncEngine) -> None:
    firmware, release, sketch = await seed_my_bench(app)

    async with firmware_work(app, MINE) as work:
        assert await work.firmwares.get(firmware.id) is not None
        assert [one.id for one in await work.firmwares.matching("")] == [firmware.id]
        assert [one.id for one in await work.firmwares.running_on(BREADBOARD)] == [firmware.id]
        assert await work.links.of_firmware(firmware.id) == (BREADBOARD,)
        assert await work.versions.firmware_of(release.id) == firmware.id
        assert [v.id for v in (await work.versions.of_firmware(firmware.id)).items] == [release.id]
        assert (await work.sources.of_version(release.id)).items == (sketch,)
        assert await work.session.scalar(EVERY_ROW) == 4


async def test_another_workspace_sees_none_of_it(app: AsyncEngine) -> None:
    # Requirements 9.1 and 9.3: by id, by name, in the list, on the revision, and every version
    # and file.
    firmware, release, _ = await seed_my_bench(app)

    async with firmware_work(app, THEIRS) as work:
        assert await work.firmwares.get(firmware.id) is None
        assert await work.firmwares.locked(firmware.id) is None
        assert await work.firmwares.named(firmware.name) is None
        assert await work.firmwares.matching("") == []
        assert await work.firmwares.matching("weather") == []
        assert await work.firmwares.running_on(BREADBOARD) == []
        assert await work.links.of_firmware(firmware.id) == ()
        assert await work.versions.get(release.id) is None
        assert await work.versions.firmware_of(release.id) is None
        assert (await work.versions.of_firmware(firmware.id)).items == ()
        assert await work.versions.summaries([firmware.id]) == {}
        assert (await work.sources.of_version(release.id)).items == ()
        # No WHERE at all: the policy is what keeps my rows out of the count.
        assert await work.session.scalar(EVERY_ROW) == 0


async def test_a_firmware_cannot_be_written_into_another_workspace(app: AsyncEngine) -> None:
    # Tagged with my workspace, pushed through theirs: `add` flushes, so the policy's WITH CHECK
    # refuses it there and then.
    async with firmware_work(app, THEIRS) as work:
        with pytest.raises(ProgrammingError, match="row-level security"):
            await work.firmwares.add(a_firmware(MINE))


async def test_a_version_cannot_be_written_into_another_workspace(app: AsyncEngine) -> None:
    # My firmware's next release, pushed through their transaction.
    firmware, _, _ = await seed_my_bench(app)

    async with firmware_work(app, THEIRS) as work:
        with pytest.raises(ProgrammingError, match="row-level security"):
            await work.versions.add(a_release(firmware, "1.1.0"))


@pytest.mark.parametrize("table", [firmware_revisions, source_files])
async def test_a_core_row_cannot_be_written_into_another_workspace(
    app: AsyncEngine, table: Table
) -> None:
    # A link or a file of my workspace, under my firmware or version, written from theirs.
    firmware, release, _ = await seed_my_bench(app)
    rows = {
        "firmware_revisions": {
            "workspace_id": MINE,
            "firmware_id": firmware.id,
            "revision_id": uuid7(),
            "created_at": NOW,
        },
        "source_files": {
            "id": uuid7(),
            "workspace_id": MINE,
            "version_id": release.id,
            "path": SourcePath("config.h"),
            "content": SourceText(""),
            "size": 0,
        },
    }

    with pytest.raises(ProgrammingError, match="row-level security"):
        async with firmware_work(app, THEIRS) as work:
            await work.session.execute(insert(table).values(**rows[table.name]))


async def test_a_write_without_a_filter_cannot_touch_another_workspace(
    app: AsyncEngine, admin: AsyncEngine
) -> None:
    firmware, release, sketch = await seed_my_bench(app)

    async with firmware_work(app, THEIRS) as work:
        # No WHERE at all: the policy is what keeps these from reaching my rows.
        await work.session.execute(text("UPDATE firmware SET name = 'Stolen'"))
        await work.session.execute(text("UPDATE firmware_versions SET changelog = NULL"))
        await work.session.execute(text("UPDATE source_files SET content = '', size = 0"))
        for table in (source_files, firmware_versions, firmware_revisions, firmware_table):
            await work.session.execute(table.delete())
        await work.clear()
        await work.commit()

    async with firmware_work(admin, MINE) as work:
        kept = await work.firmwares.get(firmware.id)
        kept_release = await work.versions.get(release.id)
        assert kept is not None
        assert kept.name == FirmwareName("Weather station")
        assert kept_release is not None
        assert kept_release.changelog == release.changelog
        assert await work.links.of_firmware(firmware.id) == (BREADBOARD,)
        assert (await work.sources.of_version(release.id)).items == (sketch,)
