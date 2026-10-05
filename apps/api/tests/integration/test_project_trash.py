"""Projects in the trash over Postgres, as `wiredex_app` (16-soft-delete-and-trash, task 5).

What only the database can show: a project in the trash and its revisions left out of every read
the repositories answer, its BOM still naming its parts, a reserve queued behind a move to the
trash finding no project and holding nothing, the cascades of a delete for good, and a restore
and a delete for good of one project taking turns.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
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
from wiredex.bootstrap.catalog import catalog_use_cases
from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.inventory import inventory_use_cases
from wiredex.bootstrap.projects import projects_use_cases
from wiredex.bootstrap.settings import Environment, Settings
from wiredex.catalog.application.categories import NewCategory
from wiredex.catalog.application.parts import NewPart
from wiredex.catalog.domain.part import PartDetails
from wiredex.catalog.domain.values import CategoryName, PartName
from wiredex.catalog.domain.values import WorkspaceId as CatalogWorkspaceId
from wiredex.inventory.application.ports import NewLocation, Receipt
from wiredex.inventory.domain.values import LocationName, Quantity
from wiredex.inventory.domain.values import PartId as InventoryPartId
from wiredex.inventory.domain.values import WorkspaceId as InventoryWorkspaceId
from wiredex.projects.application.ports import NewBomLine
from wiredex.projects.application.projects import UnitOfWorkFactory
from wiredex.projects.application.trash import DeleteProjectForGood, RestoreProject
from wiredex.projects.domain.designators import Designators
from wiredex.projects.domain.errors import (
    ProjectNotFoundError,
    RevisionHoldsStockError,
    RevisionNotFoundError,
)
from wiredex.projects.domain.filter import ProjectFilter
from wiredex.projects.domain.project import ProjectDetails
from wiredex.projects.domain.values import (
    PartId,
    ProjectId,
    ProjectName,
    RevisionId,
    Tags,
    WorkspaceId,
)
from wiredex.projects.infrastructure.unit_of_work import SqlProjectsUnitOfWork
from wiredex.shared_kernel.infrastructure.ids import Uuid7Generator

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

BENCH = WorkspaceId(uuid7())
TABLES = (
    "net_pins, nets, bom_designators, bom_lines, revisions, projects, units, stock_movements,"
    " stock_balances, stock_lots, short_code_counters, locations, pins, part_definitions,"
    " attribute_definitions, categories"
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
    ids = Uuid7Generator()
    return lambda workspace_id: SqlProjectsUnitOfWork(sessions, workspace_id, ids)


@dataclass(frozen=True, slots=True)
class Station:
    project: ProjectId
    revision: RevisionId
    part: PartId


async def a_station(sessions: async_sessionmaker[AsyncSession], name: str) -> Station:
    """A project whose revision A's BOM needs one 10k resistor, with ten of them in a drawer,
    so A can be reserved."""
    catalog, inventory = catalog_use_cases(sessions), inventory_use_cases(sessions)
    here = CatalogWorkspaceId(BENCH)
    passives = await catalog.create_category(here, NewCategory(CategoryName(f"Passives {name}")))
    part = await catalog.define_part(
        here, NewPart(passives.category.id, PartDetails(PartName(f"R 10k {name}")))
    )
    stock = InventoryWorkspaceId(BENCH)
    drawer = await inventory.create_location(stock, NewLocation(LocationName(f"Drawer {name}")))
    await inventory.receive_stock(stock, Receipt(InventoryPartId(part.id), drawer.id, Quantity(10)))
    projects = projects_use_cases(sessions)
    created = await projects.create_project(
        BENCH, ProjectDetails(ProjectName(name), tags=Tags.of(["esp32"]))
    )
    revision = created.revisions.items[0]
    await projects.add_bom_line(
        BENCH, revision.id, NewBomLine(PartId(part.id), Designators.parse("R1"))
    )
    return Station(created.project.id, revision.id, PartId(part.id))


async def test_a_project_in_the_trash_and_its_revisions_are_absent_from_every_read(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    gone = await a_station(sessions, "Weather station")
    kept = await a_station(sessions, "Greenhouse controller")
    projects = projects_use_cases(sessions)
    await projects.delete_project(BENCH, gone.project)

    async with SqlProjectsUnitOfWork(sessions, BENCH, Uuid7Generator()) as work:
        assert await work.projects.get(gone.project) is None
        assert await work.projects.locked(gone.project) is None
        listed = await work.projects.matching(ProjectFilter())
        assert [project.id for project in listed] == [kept.project]
        assert [count.tag.value for count in await work.projects.tag_counts()] == ["esp32"]
        assert [count.projects for count in await work.projects.tag_counts()] == [1]
        assert await work.revisions.get(gone.revision) is None
        assert await work.revisions.project_of(gone.revision) is None
        assert (await work.revisions.of_project(gone.project)).items == ()
        assert await work.revisions.ref(gone.revision) is None
        assert list(await work.revisions.refs([gone.revision, kept.revision])) == [kept.revision]
        # Its BOM still names its part, marked as in the trash (16's decision 4).
        uses = await work.bom_lines.uses_of(gone.part, 3)
        assert [(use.revision_id, use.in_trash) for use in uses.uses] == [(gone.revision, True)]
        # The project keeps its name (16's decision 5).
        holder = await work.projects.named(ProjectName("WEATHER station"))
        assert holder is not None
        assert holder.id == gone.project


async def test_the_trash_is_read_newest_first_a_page_in_one_statement(
    app: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    first = await a_station(sessions, "Weather station")
    second = await a_station(sessions, "Greenhouse controller")
    projects = projects_use_cases(sessions)
    await projects.delete_project(BENCH, first.project)
    await projects.delete_project(BENCH, second.project)

    async with factory(sessions)(BENCH) as work:
        with counting(app) as statements:
            page = await work.projects.trashed(10, None)
        assert [project.id for project in page.items] == [second.project, first.project]
        assert page.total == 2
        assert len(statements) == 1
        with counting(app) as narrowed:
            station = await work.projects.trashed(10, "STATION")
        assert ([project.id for project in station.items], station.total) == ([first.project], 1)
        assert len(narrowed) == 1
        assert (await work.projects.trashed(10, "%")).total == 0


async def test_a_project_deleted_for_good_takes_its_revisions_and_boms(
    admin: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    station = await a_station(sessions, "Weather station")
    await projects_use_cases(sessions).delete_project(BENCH, station.project)

    await DeleteProjectForGood(factory(sessions))(BENCH, station.project)

    async with admin.connect() as connection:
        counts = [
            await connection.scalar(text(f"SELECT count(*) FROM {table}"))  # noqa: S608
            for table in ("projects", "revisions", "bom_lines", "bom_designators")
        ]
    assert counts == [0, 0, 0, 0]


async def test_a_restored_project_is_back_with_its_bom(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    station = await a_station(sessions, "Weather station")
    projects = projects_use_cases(sessions)
    await projects.delete_project(BENCH, station.project)

    await RestoreProject(factory(sessions))(BENCH, station.project)

    bom = await projects.get_bom(BENCH, station.revision)
    assert [line.content.part_id for line in bom.bom.lines] == [station.part]


@asynccontextmanager
async def project_held(admin: AsyncEngine, project_id: UUID) -> AsyncIterator[None]:
    """The project's row locked by an outside transaction until the block ends, so the requests
    line up behind it in the order they asked for it."""
    async with admin.begin() as holder:
        await holder.execute(
            text("SELECT id FROM projects WHERE id = :id FOR UPDATE"), {"id": project_id}
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
    pytest.fail(f"expected {count} transactions waiting for the project's lock")


async def test_a_reserve_queued_behind_a_move_to_the_trash_finds_no_project(
    admin: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    # Requirement 1.5: the reserve's lock on the project is taken once the move commits, and
    # Postgres checks its `trashed_at IS NULL` again against that row. Without it the reserve
    # would hold stock for a revision of a project in the trash.
    station = await a_station(sessions, "Weather station")
    projects = projects_use_cases(sessions)

    async with project_held(admin, station.project):
        move = asyncio.create_task(projects.delete_project(BENCH, station.project))
        await until_waiting(admin, 1)
        reserve = asyncio.create_task(projects.reserve_revision(BENCH, station.revision, []))
        await until_waiting(admin, 2)
    await move

    with pytest.raises(RevisionNotFoundError):
        await reserve
    async with admin.connect() as connection:
        reserved = await connection.scalar(text("SELECT sum(reserved) FROM stock_balances"))
        status = await connection.scalar(text("SELECT status FROM revisions"))
    assert (reserved, status) == (0, "draft")


async def test_a_move_to_the_trash_queued_behind_a_reserve_is_refused(
    admin: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    # Requirements 1.3 and 1.5, the other way round: the move waits for the reserve to commit
    # and then reads the revisions fresh, so it sees A reserved and refuses. Without the lock it
    # would read A as a draft and move a project holding stock to the trash.
    station = await a_station(sessions, "Weather station")
    projects = projects_use_cases(sessions)

    async with project_held(admin, station.project):
        reserve = asyncio.create_task(projects.reserve_revision(BENCH, station.revision, []))
        await until_waiting(admin, 1)
        move = asyncio.create_task(projects.delete_project(BENCH, station.project))
        await until_waiting(admin, 2)
    await reserve

    with pytest.raises(RevisionHoldsStockError):
        await move
    async with admin.connect() as connection:
        trashed = await connection.scalar(text("SELECT trashed_at FROM projects"))
    assert trashed is None


async def test_a_restore_and_a_delete_for_good_of_one_project_take_turns(
    admin: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    # Requirement 5.4: one wins, the other finds nothing, and the project is back or gone.
    station = await a_station(sessions, "Weather station")
    await projects_use_cases(sessions).delete_project(BENCH, station.project)
    work = factory(sessions)

    async with project_held(admin, station.project):
        racing = [
            asyncio.create_task(RestoreProject(work)(BENCH, station.project)),
            asyncio.create_task(DeleteProjectForGood(work)(BENCH, station.project)),
        ]
        await until_waiting(admin, 2)
    outcomes = await asyncio.gather(*racing, return_exceptions=True)

    assert outcomes.count(None) == 1
    assert len([o for o in outcomes if isinstance(o, ProjectNotFoundError)]) == 1
    async with admin.connect() as connection:
        found = await connection.execute(text("SELECT trashed_at FROM projects"))
        rows = [tuple(row) for row in found]
    assert rows in ([(None,)], [])
