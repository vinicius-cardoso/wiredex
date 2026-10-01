"""Firmware in the trash over Postgres, as `wiredex_app` (16-soft-delete-and-trash, task 6).

What only the database can show: a firmware in the trash and its versions left out of every read
the repositories answer, its name still held, a fork copying only live firmware's links, a
version started behind a move to the trash finding no firmware, the cascades of a delete for good,
and a restore and a delete for good of one firmware taking turns.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID, uuid7

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from support.sql import counting
from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.firmware import firmware_use_cases
from wiredex.bootstrap.projects import projects_use_cases
from wiredex.bootstrap.settings import Environment, Settings
from wiredex.firmware.application.firmware import UnitOfWorkFactory
from wiredex.firmware.application.ports import NewSourceFile
from wiredex.firmware.application.trash import DeleteFirmwareForGood, RestoreFirmware
from wiredex.firmware.domain.errors import FirmwareNotFoundError
from wiredex.firmware.domain.firmware import FirmwareDetails
from wiredex.firmware.domain.values import (
    BoardTarget,
    Changelog,
    FirmwareId,
    FirmwareName,
    Framework,
    RevisionId,
    VersionId,
    WorkspaceId,
)
from wiredex.firmware.infrastructure.unit_of_work import SqlFirmwareUnitOfWork
from wiredex.projects.application.ports import NewRevision
from wiredex.projects.domain.project import ProjectDetails
from wiredex.projects.domain.values import ProjectName
from wiredex.projects.domain.values import RevisionId as ProjectsRevisionId
from wiredex.projects.domain.values import WorkspaceId as ProjectsWorkspaceId

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

BENCH = WorkspaceId(uuid7())
TABLES = (
    "flashes, source_files, firmware_versions, firmware_revisions, firmware, net_pins, nets,"
    " bom_designators, bom_lines, revisions, projects"
)


@pytest.fixture
async def admin(migrated_database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(migrated_database_url)
    yield engine
    await engine.dispose()


@pytest.fixture(autouse=True)
async def clean(admin: AsyncEngine) -> AsyncIterator[None]:
    yield
    async with admin.begin() as connection:
        await connection.execute(text(f"TRUNCATE {TABLES} CASCADE"))


@pytest.fixture
async def app(app_database_url: str) -> AsyncIterator[AsyncEngine]:
    settings = Settings(environment=Environment.TEST, database_url=SecretStr(app_database_url))
    engine = create_engine(settings)
    yield engine
    await engine.dispose()


@pytest.fixture
def sessions(app: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(app)


def factory(sessions: async_sessionmaker[AsyncSession]) -> UnitOfWorkFactory:
    return lambda workspace_id: SqlFirmwareUnitOfWork(sessions, workspace_id)


async def a_firmware(
    sessions: async_sessionmaker[AsyncSession], name: str, revision: RevisionId | None = None
) -> tuple[FirmwareId, VersionId]:
    """A firmware with `1.0.0` released, a sketch in it, running on the revision when given."""
    firmware = firmware_use_cases(sessions)
    details = FirmwareDetails(
        FirmwareName(name), BoardTarget("esp32:esp32:esp32"), Framework.ARDUINO
    )
    created = await firmware.create_firmware(BENCH, details, revision)
    draft = (await firmware.start_version(BENCH, created.firmware.id)).version
    await firmware.add_source_files(
        BENCH, draft.id, [NewSourceFile("sketch.ino", "void loop() {}\n")]
    )
    await firmware.update_version(BENCH, draft.id, draft.number, Changelog("First light."))
    await firmware.release_version(BENCH, draft.id)
    return created.firmware.id, draft.id


async def a_revision(sessions: async_sessionmaker[AsyncSession]) -> RevisionId:
    created = await projects_use_cases(sessions).create_project(
        ProjectsWorkspaceId(BENCH), ProjectDetails(ProjectName(f"Weather station {uuid7()}"))
    )
    return RevisionId(created.revisions.items[0].id)


async def test_a_firmware_in_the_trash_and_its_versions_are_absent_from_every_read(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    revision = await a_revision(sessions)
    gone, gone_version = await a_firmware(sessions, "Weather station", revision)
    kept, _ = await a_firmware(sessions, "Greenhouse controller", revision)
    await firmware_use_cases(sessions).delete_firmware(BENCH, gone)

    async with factory(sessions)(BENCH) as work:
        assert await work.firmwares.get(gone) is None
        assert await work.firmwares.locked(gone) is None
        assert [one.id for one in await work.firmwares.matching("")] == [kept]
        assert [one.id for one in await work.firmwares.running_on(revision)] == [kept]
        assert await work.versions.get(gone_version) is None
        assert await work.versions.firmware_of(gone_version) is None
        assert (await work.versions.of_firmware(gone)).items == ()
        holder = await work.firmwares.named(FirmwareName("WEATHER station"))
        assert holder is not None
        assert holder.id == gone


async def test_the_trash_is_read_newest_first_a_page_in_one_statement(
    app: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    first, _ = await a_firmware(sessions, "Weather station")
    second, _ = await a_firmware(sessions, "Greenhouse controller")
    firmware = firmware_use_cases(sessions)
    await firmware.delete_firmware(BENCH, first)
    await firmware.delete_firmware(BENCH, second)

    async with factory(sessions)(BENCH) as work:
        with counting(app) as statements:
            page = await work.firmwares.trashed(None, 10)
        assert [one.id for one in page] == [second, first]
        assert len(statements) == 1


async def test_a_fork_copies_only_the_links_of_live_firmware(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Requirement 2.4: the firmware in the trash is absent, so its link stays behind.
    revision = await a_revision(sessions)
    gone, _ = await a_firmware(sessions, "Weather station", revision)
    kept, _ = await a_firmware(sessions, "Greenhouse controller", revision)
    firmware = firmware_use_cases(sessions)
    await firmware.delete_firmware(BENCH, gone)

    fork = await projects_use_cases(sessions).fork_revision(
        ProjectsWorkspaceId(BENCH), ProjectsRevisionId(revision), NewRevision()
    )

    async with factory(sessions)(BENCH) as work:
        assert [one.id for one in await work.firmwares.running_on(RevisionId(fork.id))] == [kept]
    # Restored, the firmware runs on the revisions it ran on, and not on the fork.
    await RestoreFirmware(factory(sessions))(BENCH, gone)
    async with factory(sessions)(BENCH) as work:
        assert set(await work.links.of_firmware(gone)) == {revision}


async def test_a_firmware_deleted_for_good_takes_its_versions_files_and_links(
    admin: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    revision = await a_revision(sessions)
    firmware_id, _ = await a_firmware(sessions, "Weather station", revision)
    await firmware_use_cases(sessions).delete_firmware(BENCH, firmware_id)

    await DeleteFirmwareForGood(factory(sessions))(BENCH, firmware_id)

    async with admin.connect() as connection:
        counts = [
            await connection.scalar(text(f"SELECT count(*) FROM {table}"))  # noqa: S608
            for table in ("firmware", "firmware_versions", "source_files", "firmware_revisions")
        ]
    assert counts == [0, 0, 0, 0]


@asynccontextmanager
async def firmware_held(admin: AsyncEngine, firmware_id: UUID) -> AsyncIterator[None]:
    """The firmware's row locked by an outside transaction until the block ends, so the
    requests line up behind it in the order they asked for it."""
    async with admin.begin() as holder:
        await holder.execute(
            text("SELECT id FROM firmware WHERE id = :id FOR UPDATE"), {"id": firmware_id}
        )
        yield


async def until_waiting(admin: AsyncEngine, count: int) -> None:
    for _ in range(200):
        async with admin.connect() as watcher:
            waiting = await watcher.scalar(
                text("SELECT count(*) FROM pg_stat_activity WHERE wait_event_type = 'Lock'")
            )
        if (waiting or 0) >= count:
            return
        await asyncio.sleep(0.05)
    pytest.fail(f"expected {count} transactions waiting for the firmware's lock")


async def test_a_version_started_behind_a_move_to_the_trash_finds_no_firmware(
    admin: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    # Requirement 1.5: the start's lock is taken once the move commits, and Postgres checks its
    # `trashed_at IS NULL` again against that row. Without it the start would add a draft to a
    # firmware in the trash.
    firmware_id, _ = await a_firmware(sessions, "Weather station")
    firmware = firmware_use_cases(sessions)

    async with firmware_held(admin, firmware_id):
        move = asyncio.create_task(firmware.delete_firmware(BENCH, firmware_id))
        await until_waiting(admin, 1)
        start = asyncio.create_task(firmware.start_version(BENCH, firmware_id))
        await until_waiting(admin, 2)
    await move

    with pytest.raises(FirmwareNotFoundError):
        await start
    async with admin.connect() as connection:
        versions = await connection.scalar(text("SELECT count(*) FROM firmware_versions"))
    assert versions == 1


async def test_a_restore_and_a_delete_for_good_of_one_firmware_take_turns(
    admin: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    # Requirement 5.4: one wins, the other finds nothing, and the firmware is back or gone.
    firmware_id, _ = await a_firmware(sessions, "Weather station")
    await firmware_use_cases(sessions).delete_firmware(BENCH, firmware_id)
    work = factory(sessions)

    async with firmware_held(admin, firmware_id):
        racing = [
            asyncio.create_task(RestoreFirmware(work)(BENCH, firmware_id)),
            asyncio.create_task(DeleteFirmwareForGood(work)(BENCH, firmware_id)),
        ]
        await until_waiting(admin, 2)
    outcomes = await asyncio.gather(*racing, return_exceptions=True)

    assert outcomes.count(None) == 1
    assert len([o for o in outcomes if isinstance(o, FirmwareNotFoundError)]) == 1
    async with admin.connect() as connection:
        found = await connection.execute(text("SELECT trashed_at FROM firmware"))
        rows = [tuple(row) for row in found]
    assert rows in ([(None,)], [])
