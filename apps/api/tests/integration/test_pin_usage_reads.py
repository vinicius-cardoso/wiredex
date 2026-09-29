"""A part's pin usage over Postgres, as `wiredex_app` (12-wiring-validation, requirement 7).

What only the real join can show: a read costs five statements whatever the number of projects,
revisions and nets, the workspace setting included (7.5); uses come by project name folded,
then revision, then designator in its canonical order, R2 before R10 (7.4); every revision
status counts (7.1); and another bench's nets on the same designators are unseen (8.1).
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
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

from support.identity import NewIds
from support.sql import counting
from wiredex.bootstrap.catalog import catalog_use_cases
from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.netlist import SqlNetlistUnitOfWork
from wiredex.bootstrap.projects import projects_use_cases
from wiredex.bootstrap.settings import Environment, Settings
from wiredex.catalog.api.router import CatalogUseCases
from wiredex.catalog.application.categories import NewCategory
from wiredex.catalog.application.parts import NewPart
from wiredex.catalog.domain.part import PartDetails
from wiredex.catalog.domain.pinout import RawPin
from wiredex.catalog.domain.values import CategoryId, CategoryName, PartDefinitionId, PartName
from wiredex.catalog.domain.values import WorkspaceId as CatalogWorkspaceId
from wiredex.projects.api.router import ProjectsUseCases
from wiredex.projects.application.netlist import AddNet, GetPinUsage, NetlistUnitOfWorkFactory
from wiredex.projects.application.ports import NewBomLine
from wiredex.projects.domain.designators import Designators
from wiredex.projects.domain.errors import PartNotFoundError
from wiredex.projects.domain.netlist import NetDraft
from wiredex.projects.domain.project import ProjectDetails
from wiredex.projects.domain.values import (
    PartId,
    ProjectName,
    RevisionId,
    RevisionStatus,
    WorkspaceId,
)
from wiredex.shared_kernel.infrastructure.clock import SystemClock

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

BENCH = WorkspaceId(uuid7())
OTHER = WorkspaceId(uuid7())
TABLES = (
    "net_pins, nets, bom_designators, bom_lines, revisions, projects, pins, part_definitions,"
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


@dataclass(frozen=True, slots=True)
class Bench:
    catalog: CatalogUseCases
    projects: ProjectsUseCases
    get_pin_usage: GetPinUsage
    add_net: AddNet

    async def part(self, name: str, *pins: RawPin, workspace_id: WorkspaceId = BENCH) -> PartId:
        where = CatalogWorkspaceId(workspace_id)
        category = await self.catalog.create_category(
            where, NewCategory(CategoryName(f"{name} parts"))
        )
        part = await self.catalog.define_part(
            where, NewPart(CategoryId(category.category.id), PartDetails(PartName(name)))
        )
        if pins:
            await self.catalog.replace_pinout(where, PartDefinitionId(part.id), pins)
        return PartId(part.id)

    async def revision(self, project: str, workspace_id: WorkspaceId = BENCH) -> RevisionId:
        view = await self.projects.create_project(
            workspace_id, ProjectDetails(ProjectName(project))
        )
        latest = view.revisions.latest
        assert latest is not None
        return latest.id

    async def line(
        self, revision: RevisionId, part: PartId, designators: str, workspace: WorkspaceId = BENCH
    ) -> None:
        await self.projects.add_bom_line(
            workspace, revision, NewBomLine(part, Designators.parse(designators), None)
        )

    async def net(
        self, revision: RevisionId, name: str, pins: str, workspace: WorkspaceId = BENCH
    ) -> None:
        await self.add_net(workspace, revision, NetDraft.parse(name, None, None, pins))


@pytest.fixture
def bench(app: AsyncEngine) -> Bench:
    sessions = create_session_factory(app)
    return Bench(
        catalog_use_cases(sessions),
        projects_use_cases(sessions),
        GetPinUsage(_netlist_work(sessions)),
        AddNet(_netlist_work(sessions), SystemClock(), NewIds()),
    )


def _netlist_work(sessions: async_sessionmaker[AsyncSession]) -> NetlistUnitOfWorkFactory:
    ids = NewIds()
    return lambda workspace_id: SqlNetlistUnitOfWork(sessions, workspace_id, ids)


def _board(count: int) -> tuple[RawPin, ...]:
    return tuple(RawPin(number=str(pin), label=f"P{pin}", type="io") for pin in range(1, count + 1))


async def test_a_read_costs_five_statements_and_orders_the_uses(
    bench: Bench, admin: AsyncEngine, app: AsyncEngine
) -> None:
    board = await bench.part("DevKit", *_board(4))
    weather = await bench.revision("Weather station")
    greenhouse = await bench.revision("greenhouse")
    lamp = await bench.revision("Lamp")
    for revision in (weather, greenhouse, lamp):
        await bench.line(revision, board, "U2, U10")
    await bench.net(weather, "SDA", "U10.1, U2.1")
    await bench.net(weather, "SCL", "U2.2")
    await bench.net(greenhouse, "SDA", "U2.1, U10.1")
    await bench.net(lamp, "PWM", "U2.1, U2.3")
    # A built revision's wiring counts as a draft's (requirement 7.1).
    async with admin.begin() as connection:
        await connection.execute(
            text("UPDATE revisions SET status = 'built' WHERE id = :id"), {"id": lamp}
        )

    with counting(app) as statements:
        usage = await bench.get_pin_usage(BENCH, board)

    # The setting, the part, its category tree, the pinout and the uses.
    assert len(statements) == 5, statements
    (pin_1, uses), (_, scl), (_, pwm), (_, free) = usage.pins
    assert [(str(u.project_name), str(u.designator), str(u.net_name)) for u in uses] == [
        ("greenhouse", "U2", "SDA"),
        ("greenhouse", "U10", "SDA"),
        ("Lamp", "U2", "PWM"),
        ("Weather station", "U2", "SDA"),
        ("Weather station", "U10", "SDA"),
    ]
    assert str(pin_1.number) == "1"
    assert [str(u.net_name) for u in scl] == ["SCL"]
    assert free == ()
    assert uses[2].status is RevisionStatus.BUILT
    assert [str(u.net_name) for u in pwm] == ["PWM"]
    assert usage.others == ()


async def test_another_benchs_part_is_not_found_and_its_nets_unseen(bench: Bench) -> None:
    board = await bench.part("DevKit", *_board(2))
    mine = await bench.revision("Weather station")
    await bench.line(mine, board, "U1")
    theirs_board = await bench.part("DevKit", *_board(2), workspace_id=OTHER)
    theirs = await bench.revision("Weather station", OTHER)
    await bench.line(theirs, theirs_board, "U1", OTHER)
    await bench.net(theirs, "SDA", "U1.1", OTHER)

    usage = await bench.get_pin_usage(BENCH, board)
    with pytest.raises(PartNotFoundError):
        await bench.get_pin_usage(BENCH, theirs_board)

    assert all(uses == () for _, uses in usage.pins)
    assert usage.others == ()
