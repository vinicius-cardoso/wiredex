"""Firmware's reads over Postgres, as `wiredex_app`, on `SqlRunsOnUnitOfWork`'s one session.

What only the real wiring can show (13-firmware-versions decision 5): projects' revisions are
read in firmware's own transaction, under its one workspace setting. So each read costs a fixed
number of statements whatever the numbers of firmware, versions, files and links, the setting
included (decision 12, requirement 12.3); a firmware names each revision it runs on by its
project, label and summary, in link order (3.5); a revision deleted after it was linked is left
out and its link kept (3.6); and another bench's revision is one the workspace doesn't hold
(3.7, 9.2).
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid7

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from support.identity import ManualClock, NewIds
from support.sql import counting
from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.firmware import SqlRunsOnUnitOfWork
from wiredex.bootstrap.projects import projects_use_cases
from wiredex.bootstrap.settings import Environment, Settings
from wiredex.firmware.application.firmware import (
    CreateFirmware,
    GetFirmware,
    ListFirmware,
    ListRevisionFirmware,
    RunsOnUnitOfWorkFactory,
)
from wiredex.firmware.application.links import LinkRevision
from wiredex.firmware.application.ports import NewSourceFile, RevisionFacts
from wiredex.firmware.application.sources import AddSourceFiles
from wiredex.firmware.application.versions import GetVersion, StartVersion
from wiredex.firmware.domain.errors import RevisionNotFoundError
from wiredex.firmware.domain.firmware import FirmwareDetails
from wiredex.firmware.domain.values import (
    BoardTarget,
    FirmwareId,
    FirmwareName,
    Framework,
    RevisionId,
    VersionId,
    WorkspaceId,
)
from wiredex.projects.application.ports import NewRevision, ProjectView
from wiredex.projects.domain.project import ProjectDetails
from wiredex.projects.domain.values import ProjectName, Summary
from wiredex.projects.domain.values import WorkspaceId as ProjectsWorkspaceId

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

NOW = datetime(2026, 9, 30, 3, tzinfo=UTC)
BENCH = WorkspaceId(uuid7())
OTHER = WorkspaceId(uuid7())
TABLES = "source_files, firmware_versions, firmware_revisions, firmware, revisions, projects"

# Every firmware and every link, counted by the owner, whom no policy narrows.
WRITTEN = text("SELECT (SELECT count(*) FROM firmware), (SELECT count(*) FROM firmware_revisions)")


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
        await connection.execute(text(f"TRUNCATE {TABLES} CASCADE"))


@pytest.fixture
async def app(app_database_url: str) -> AsyncIterator[AsyncEngine]:
    """The API's role, with the API's engine: row security applies."""
    settings = Settings(environment=Environment.TEST, database_url=SecretStr(app_database_url))
    engine = create_engine(settings)
    yield engine
    await engine.dispose()


def _runs_on_work(sessions: async_sessionmaker[AsyncSession]) -> RunsOnUnitOfWorkFactory:
    return lambda workspace_id: SqlRunsOnUnitOfWork(sessions, workspace_id)


class Bench:
    """Projects' use cases as the app wires them, and firmware's over `SqlRunsOnUnitOfWork`, one
    factory serving every one of them (decision 5), on a clock the test moves."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        work = _runs_on_work(sessions)
        ids = NewIds()
        self.clock = ManualClock(NOW)
        self.projects = projects_use_cases(sessions)
        self.create_firmware = CreateFirmware(work, self.clock, ids)
        self.link_revision = LinkRevision(work, self.clock)
        self.start_version = StartVersion(work, self.clock, ids)
        self.add_source_files = AddSourceFiles(work, self.clock, ids)
        self.get_firmware = GetFirmware(work)
        self.list_firmware = ListFirmware(work)
        self.list_revision_firmware = ListRevisionFirmware(work)
        self.get_version = GetVersion(work)

    async def project(self, name: str, workspace_id: WorkspaceId = BENCH) -> ProjectView:
        return await self.projects.create_project(
            ProjectsWorkspaceId(workspace_id), ProjectDetails(ProjectName(name))
        )

    async def revision(self, workspace_id: WorkspaceId = BENCH) -> RevisionId:
        """Revision A of a project of its own, named apart, so a bench holds any number."""
        return first_revision(await self.project(f"Weather station {uuid7()}", workspace_id))

    async def firmware(self, name: str, revision: RevisionId | None = None) -> FirmwareId:
        view = await self.create_firmware(BENCH, details(name), revision)
        return view.firmware.id

    async def version(self, firmware: FirmwareId, base: VersionId | None = None) -> VersionId:
        """The firmware's next draft, empty or holding a copy of every file of its base."""
        view = await self.start_version(BENCH, firmware, base_id=base)
        return view.version.id

    async def sketch(self, version: VersionId, files: int) -> None:
        """A sketch and the headers beside it, `files` in all, in one batch."""
        headers = [NewSourceFile(f"lib/sensor_{n}.h", "#pragma once\n") for n in range(1, files)]
        sketch = NewSourceFile("weather_station.ino", "void setup() {}\nvoid loop() {}\n")
        await self.add_source_files(BENCH, version, [sketch, *headers])


@pytest.fixture
def bench(app: AsyncEngine) -> Bench:
    return Bench(create_session_factory(app))


def details(name: str) -> FirmwareDetails:
    return FirmwareDetails(FirmwareName(name), BoardTarget("esp32:esp32:esp32"), Framework.ARDUINO)


def first_revision(view: ProjectView) -> RevisionId:
    """Revision A, which a new project starts with, as firmware names it."""
    latest = view.revisions.latest
    assert latest is not None
    return RevisionId(latest.id)


# --- What each read costs, whatever its sizes (decision 12) ----------------------------------


@pytest.mark.parametrize("count", [1, 40])
async def test_a_firmwares_page_costs_five_statements_whatever_its_sizes(
    bench: Bench, app: AsyncEngine, count: int
) -> None:
    # `count` revisions linked, and `count` versions of `count` files each: the first holds a
    # batch, and each later one a copy of the one before.
    revisions = [await bench.revision() for _ in range(count)]
    station = await bench.firmware("Weather station", revisions[0])
    for revision in revisions[1:]:
        await bench.link_revision(BENCH, station, revision)
    versions = [await bench.version(station)]
    await bench.sketch(versions[0], count)
    for _ in range(count - 1):
        versions.append(await bench.version(station, versions[-1]))

    with counting(app) as statements:
        view = await bench.get_firmware(BENCH, station)

    # Row-level security would hide the revisions from a read outside the one setting.
    assert sorted(facts.revision_id for facts in view.runs_on) == sorted(revisions)
    assert [summary.files for summary in view.versions] == [count] * count
    # The setting, the firmware, its versions with their files counted and sized, its links,
    # and the revisions they name.
    assert len(statements) == 5, statements


@pytest.mark.parametrize("count", [1, 40])
async def test_the_list_costs_three_statements_and_a_revisions_firmware_four(
    bench: Bench, app: AsyncEngine, count: int
) -> None:
    revision = await bench.revision()
    for number in range(count):
        firmware = await bench.firmware(f"Logger {number:02}", revision)
        await bench.version(firmware)

    with counting(app) as listing:
        rows = await bench.list_firmware(BENCH)
    with counting(app) as running:
        running_on = await bench.list_revision_firmware(BENCH, revision)

    assert [row.versions for row in rows] == [1] * count
    assert [row.firmware.name.value for row in running_on] == [
        f"Logger {number:02}" for number in range(count)
    ]
    # The setting, the firmware matching, and their versions with their files counted.
    assert len(listing) == 3, listing
    # The setting, the revision, the firmware its links name, and their versions.
    assert len(running) == 4, running


@pytest.mark.parametrize("count", [1, 40])
async def test_a_version_costs_four_statements_whatever_its_files(
    bench: Bench, app: AsyncEngine, count: int
) -> None:
    station = await bench.firmware("Weather station")
    base = await bench.version(station)
    await bench.sketch(base, count)
    draft = await bench.version(station, base)

    with counting(app) as statements:
        view = await bench.get_version(BENCH, draft)

    assert view.base is not None
    assert view.base.id == base
    assert len(view.files.items) == count
    # The setting, the version, its base and its files.
    assert len(statements) == 4, statements


# --- The revisions a firmware runs on, as projects holds them --------------------------------


async def test_a_firmware_names_its_revisions_in_link_order_and_leaves_out_those_gone(
    bench: Bench, app: AsyncEngine
) -> None:
    # Requirements 3.5 and 3.6 (decision 3): each revision by its project, label and summary,
    # in the order it was linked, which is neither the ids' nor the names'. A revision deleted
    # alone or with its project is left out, and its link kept for the trash to bring back.
    here = ProjectsWorkspaceId(BENCH)
    station = await bench.project("Weather station")
    greenhouse = await bench.project("Greenhouse controller")
    breadboard, controller = first_revision(station), first_revision(greenhouse)
    added = await bench.projects.add_revision(
        here, station.project.id, NewRevision(summary=Summary("perfboard"))
    )
    perfboard = RevisionId(added.id)
    firmware = await bench.firmware("Weather station", perfboard)
    for revision in (controller, breadboard):
        bench.clock.advance(timedelta(minutes=1))
        await bench.link_revision(BENCH, firmware, revision)

    before = await bench.get_firmware(BENCH, firmware)
    await bench.projects.delete_revision(here, added.id)
    await bench.projects.delete_project(here, greenhouse.project.id)
    after = await bench.get_firmware(BENCH, firmware)

    assert before.runs_on == (
        RevisionFacts(perfboard, station.project.id, "Weather station", "B", "perfboard"),
        RevisionFacts(controller, greenhouse.project.id, "Greenhouse controller", "A", None),
        RevisionFacts(breadboard, station.project.id, "Weather station", "A", None),
    )
    assert after.runs_on == before.runs_on[2:]
    async with SqlRunsOnUnitOfWork(create_session_factory(app), BENCH) as work:
        assert await work.links.of_firmware(firmware) == (perfboard, controller, breadboard)
    # Asked for by id, the revision that went is one the workspace doesn't hold.
    with pytest.raises(RevisionNotFoundError):
        await bench.list_revision_firmware(BENCH, perfboard)


async def test_another_benchs_revision_is_not_found_and_nothing_is_written(
    bench: Bench, admin: AsyncEngine
) -> None:
    # Requirements 3.7 and 9.2: row-level security hides their revision from the one read that
    # asks, so whichever use case names it answers not found, as for a deleted one.
    theirs = await bench.revision(OTHER)
    mine = await bench.firmware("Weather station")

    with pytest.raises(RevisionNotFoundError):
        await bench.create_firmware(BENCH, details("Greenhouse controller"), theirs)
    with pytest.raises(RevisionNotFoundError):
        await bench.link_revision(BENCH, mine, theirs)
    with pytest.raises(RevisionNotFoundError):
        await bench.list_revision_firmware(BENCH, theirs)

    # Their own bench holds it: the workspace refused it, not the id.
    assert await bench.list_revision_firmware(OTHER, theirs) == []
    async with admin.connect() as connection:
        written = await connection.execute(WRITTEN)
        # My one firmware, and no link.
        assert tuple(written.one()) == (1, 0)
