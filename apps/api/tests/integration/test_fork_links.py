"""A fork carrying the firmware its source runs, over Postgres, as `wiredex_app`.

What only the real wiring can show (13-firmware-versions decision 4): `SqlForkUnitOfWork` binds
firmware's links on the session projects' unit of work opened, so a fork made through
`projects_use_cases` runs its source's firmware, copied after 09's BOM lines and 11's nets in the
fork's one transaction, under its one workspace setting (requirement 4.1). The source's links and
every other revision's stay as they were (4.2); a content failing after the links keeps no link,
as it keeps no fork (4.3); and a revision is forked with its links whatever its status, with
`ForkRevision` unchanged (4.4).
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import NamedTuple, Self
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

from support.identity import ManualClock, NewIds
from support.netlist import content_of
from support.projects import CopyFailedError, FailingContent
from support.sql import committing, counting, row_counts
from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.firmware import SqlRunsOnUnitOfWork
from wiredex.bootstrap.fork import FirmwareLinksContent, SqlForkUnitOfWork
from wiredex.bootstrap.projects import projects_use_cases
from wiredex.bootstrap.settings import Environment, Settings
from wiredex.firmware.application.firmware import CreateFirmware, RunsOnUnitOfWorkFactory
from wiredex.firmware.application.links import LinkRevision
from wiredex.firmware.domain.firmware import FirmwareDetails
from wiredex.firmware.domain.values import BoardTarget, FirmwareId, FirmwareName, Framework
from wiredex.firmware.domain.values import RevisionId as FirmwareRevisionId
from wiredex.firmware.domain.values import WorkspaceId as FirmwareWorkspaceId
from wiredex.projects.application.bom import CopyBomLines
from wiredex.projects.application.netlist import CopyNetlist
from wiredex.projects.application.ports import NewRevision
from wiredex.projects.application.revisions import ForkRevision
from wiredex.projects.domain.bom import BomLine, LineContent
from wiredex.projects.domain.designators import Designators
from wiredex.projects.domain.netlist import Net, NetContent
from wiredex.projects.domain.project import ProjectDetails
from wiredex.projects.domain.revision import Revision
from wiredex.projects.domain.values import (
    BomLineId,
    NetId,
    PartId,
    ProjectName,
    RevisionStatus,
    WorkspaceId,
)
from wiredex.projects.infrastructure.unit_of_work import SqlProjectsUnitOfWork

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

NOW = datetime(2026, 9, 30, 3, tzinfo=UTC)
BENCH = WorkspaceId(uuid7())
SENSOR = PartId(uuid7())
# What a sample revision holds besides its firmware: a BOM line, and a net on one of its pins.
LINE = LineContent.of(SENSOR, Designators.parse("U2"), None, None)
NET = content_of("SDA", "U2.3")
TABLES = (
    "firmware_revisions, firmware, net_pins, nets, bom_designators, bom_lines, revisions, projects"
)


class Link(NamedTuple):
    """A row of `firmware_revisions`: a firmware, a revision it runs on, and when it was linked."""

    firmware_id: UUID
    revision_id: UUID
    created_at: datetime


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
    """Projects' use cases as the app wires them, the fork among them, and firmware's create and
    link over `SqlRunsOnUnitOfWork`, on a clock the test moves."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        work = _runs_on_work(sessions)
        ids = NewIds()
        self._sessions = sessions
        self._clock = ManualClock(NOW)
        self.projects = projects_use_cases(sessions)
        self._create_firmware = CreateFirmware(work, self._clock, ids)
        self._link_revision = LinkRevision(work, self._clock)

    async def revision(self, name: str = "Weather station") -> Revision:
        """Revision A of a new project, holding `LINE` and `NET`."""
        view = await self.projects.create_project(BENCH, ProjectDetails(ProjectName(name)))
        revision = view.revisions.items[0]
        async with SqlProjectsUnitOfWork(self._sessions, BENCH, NewIds()) as work:
            await work.bom_lines.add(BomLine.on(revision, BomLineId(uuid7()), LINE, NOW))
            await work.nets.add(Net.on(revision, NetId(uuid7()), NET, NOW))
            await work.commit()
        return revision

    async def firmware(self, name: str, *runs_on: Revision) -> FirmwareId:
        """A firmware running on the revisions, each linked a minute after the one before."""
        workspace = FirmwareWorkspaceId(BENCH)
        details = FirmwareDetails(
            FirmwareName(name), BoardTarget("esp32:esp32:esp32"), Framework.ARDUINO
        )
        view = await self._create_firmware(workspace, details)
        for revision in runs_on:
            self._clock.advance(timedelta(minutes=1))
            await self._link_revision(workspace, view.firmware.id, FirmwareRevisionId(revision.id))
        return view.firmware.id

    async def fork(self, source: Revision) -> Revision:
        return await self.projects.fork_revision(BENCH, source.id, NewRevision())

    async def contents(self, revision: Revision) -> tuple[list[LineContent], list[NetContent]]:
        """What the revision's BOM lines and nets hold, their ids aside."""
        async with SqlProjectsUnitOfWork(self._sessions, BENCH, NewIds()) as work:
            bom = await work.bom_lines.of_revision(revision.id)
            netlist = await work.nets.of_revision(revision.id)
        return [line.content for line in bom.lines], [net.content for net in netlist.nets]


@pytest.fixture
def bench(app: AsyncEngine) -> Bench:
    return Bench(create_session_factory(app))


async def links(admin: AsyncEngine) -> set[Link]:
    """Every link of every workspace, read by the owner, whom no policy narrows."""
    async with admin.connect() as connection:
        rows = await connection.execute(
            text("SELECT firmware_id, revision_id, created_at FROM firmware_revisions")
        )
        return {Link(*row) for row in rows}


async def running_on(admin: AsyncEngine, revision: Revision) -> dict[UUID, datetime]:
    """The firmware linked to the revision, each with the date of its link."""
    return {
        link.firmware_id: link.created_at
        for link in await links(admin)
        if link.revision_id == revision.id
    }


async def last_changes(admin: AsyncEngine) -> dict[UUID, datetime]:
    """Each firmware's last change, which orders the firmware list (requirement 2.2)."""
    async with admin.connect() as connection:
        rows = await connection.execute(text("SELECT id, updated_at FROM firmware"))
        return {row.id: row.updated_at for row in rows}


# --- What a fork copies, and in what order (requirement 4.1) ---------------------------------


async def test_the_links_are_the_last_content_a_fork_copies(app: AsyncEngine) -> None:
    # 09's lines first and 11's nets after them, as the base registers them, then firmware's.
    async with SqlForkUnitOfWork(create_session_factory(app), BENCH, NewIds()) as work:
        registered = [type(content) for content in work.revision_contents]

    assert registered == [CopyBomLines, CopyNetlist, FirmwareLinksContent]


async def test_a_fork_runs_its_sources_firmware_copied_with_its_bom_and_nets_in_one_commit(
    bench: Bench, app: AsyncEngine, admin: AsyncEngine
) -> None:
    # Through `ForkRevision` as `projects_use_cases` wires it: the fork's lines, nets and links
    # land with it in one commit, each link dated when the fork was made.
    source = await bench.revision()
    station = await bench.firmware("Weather station", source)
    logger = await bench.firmware("Logger", source)

    with committing(app) as commits:
        fork = await bench.fork(source)

    assert len(commits) == 1
    assert await bench.contents(fork) == ([LINE], [NET])
    assert await running_on(admin, fork) == {station: fork.created_at, logger: fork.created_at}
    # Each now runs on one more revision, so each moves up the firmware list (requirement 2.2).
    assert await last_changes(admin) == {station: fork.created_at, logger: fork.created_at}


async def test_a_fork_leaves_the_sources_links_and_every_other_revisions_as_they_were(
    bench: Bench, admin: AsyncEngine
) -> None:
    # Requirement 4.2: a sibling of the source and another project's revision run firmware too.
    # The only new row names the fork, and every other row, its date included, is as it was.
    source = await bench.revision()
    sibling = await bench.projects.add_revision(BENCH, source.project_id, NewRevision())
    elsewhere = await bench.revision("Greenhouse controller")
    station = await bench.firmware("Weather station", source, sibling, elsewhere)
    await bench.firmware("Logger", sibling)
    await bench.firmware("Greenhouse controller", elsewhere)
    before = await links(admin)

    fork = await bench.fork(source)

    after = await links(admin)
    assert {link for link in after if link.revision_id != fork.id} == before
    assert after - before == {Link(station, fork.id, fork.created_at)}


@pytest.mark.parametrize(
    "status", [RevisionStatus.RESERVED, RevisionStatus.BUILT, RevisionStatus.DISMANTLED]
)
async def test_a_revision_past_draft_is_forked_with_its_links(
    bench: Bench, admin: AsyncEngine, status: RevisionStatus
) -> None:
    # Requirement 4.4: no status locks a link (decision 2), so a fork copies them whatever the
    # source's. The status is placed by hand, as the pin-usage tests place one.
    source = await bench.revision()
    station = await bench.firmware("Weather station", source)
    async with admin.begin() as connection:
        await connection.execute(
            text("UPDATE revisions SET status = :status WHERE id = :id"),
            {"status": status.value, "id": source.id},
        )

    fork = await bench.fork(source)

    assert fork.status is RevisionStatus.DRAFT
    assert await running_on(admin, fork) == {station: fork.created_at}


# --- A fork that fails (requirement 4.3) ------------------------------------------------------


class LinksThenFailUnitOfWork(SqlForkUnitOfWork):
    """The fork's unit of work with a content that fails registered after the links' copy."""

    async def __aenter__(self) -> Self:
        await super().__aenter__()
        self.revision_contents = (*self.revision_contents, FailingContent())
        return self


async def test_a_content_failing_after_the_links_keeps_no_link_and_no_fork(
    bench: Bench, app: AsyncEngine, admin: AsyncEngine
) -> None:
    # The links were copied and their firmware moved, then the rollback took them with the fork,
    # its lines and its nets.
    source = await bench.revision()
    await bench.firmware("Weather station", source)
    sessions = create_session_factory(app)
    ids = NewIds()
    fork = ForkRevision(
        lambda workspace_id: LinksThenFailUnitOfWork(sessions, workspace_id, ids),
        ManualClock(NOW + timedelta(hours=1)),
        ids,
    )
    rows, before, changed = await row_counts(admin), await links(admin), await last_changes(admin)

    with counting(app) as statements, pytest.raises(CopyFailedError):
        await fork(BENCH, source.id, NewRevision())

    copied = [
        statement
        for statement in statements
        if statement.startswith(("INSERT INTO firmware_revisions ", "UPDATE firmware "))
    ]
    assert len(copied) == 2, statements
    assert await row_counts(admin) == rows
    assert await links(admin) == before
    assert await last_changes(admin) == changed
