"""A netlist over Postgres, as `wiredex_app`, on `SqlNetlistUnitOfWork`'s one session.

What only the real wiring can show (11-netlist-editor): a read costs nine statements whatever
the netlist's size, the workspace setting included (requirement 7.3); a write reads a fixed
number of times and writes a net's references in one statement (11.3); a pinout replaced and a
BOM line renumbered after a net was written leave the net as it was and change what its
references resolve to (4.4); and another bench's nets, designators and parts are unseen (8).
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
from wiredex.projects.application.netlist import AddNet, GetNetlist, NetlistUnitOfWorkFactory
from wiredex.projects.application.ports import NewBomLine
from wiredex.projects.domain.designators import Designators
from wiredex.projects.domain.errors import UnknownDesignatorError
from wiredex.projects.domain.netlist import NetDraft, ResolutionState
from wiredex.projects.domain.project import ProjectDetails
from wiredex.projects.domain.values import PartId, ProjectName, RevisionId, WorkspaceId
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
    get_netlist: GetNetlist
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

    async def revision(self, workspace_id: WorkspaceId = BENCH) -> RevisionId:
        view = await self.projects.create_project(
            workspace_id, ProjectDetails(ProjectName(f"Weather station {uuid7()}"))
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
        GetNetlist(_netlist_work(sessions)),
        AddNet(_netlist_work(sessions), SystemClock(), NewIds()),
    )


def _netlist_work(sessions: async_sessionmaker[AsyncSession]) -> NetlistUnitOfWorkFactory:
    ids = NewIds()
    return lambda workspace_id: SqlNetlistUnitOfWork(sessions, workspace_id, ids)


def _board(count: int) -> tuple[RawPin, ...]:
    return tuple(RawPin(number=str(pin), label=f"P{pin}", type="io") for pin in range(1, count + 1))


@pytest.mark.parametrize(("nets", "parts"), [(1, 1), (60, 40)])
async def test_a_netlist_read_costs_nine_statements_whatever_its_size(
    bench: Bench, app: AsyncEngine, nets: int, parts: int
) -> None:
    revision = await bench.revision()
    for index in range(parts):
        part = await bench.part(f"Part {index}", *_board(4))
        await bench.line(revision, part, f"U{index + 1}")
    for index in range(nets):
        await bench.net(revision, f"N{index}", f"U{index % parts + 1}.1, U{index % parts + 1}.2")

    with counting(app) as statements:
        view = await bench.get_netlist(BENCH, revision)

    assert len(view.netlist.nets) == nets
    # The setting, the revision, the lines, their designators, the nets, their references, the
    # parts, the category tree and the pins.
    assert len(statements) == 9, statements


async def test_a_write_reads_a_fixed_number_of_times_and_inserts_references_once(
    bench: Bench, app: AsyncEngine
) -> None:
    revision = await bench.revision()
    board = await bench.part("DevKit", *_board(40))
    await bench.line(revision, board, "U1")

    with counting(app) as statements:
        await bench.net(revision, "BUS", ", ".join(f"U1.{pin}" for pin in range(1, 30)))

    inserts = [s for s in statements if s.lstrip().upper().startswith("INSERT INTO NET_PINS")]
    assert len(inserts) == 1
    assert len(statements) < 25, statements


async def test_a_pinout_or_bom_edit_leaves_the_net_and_changes_its_resolutions(
    bench: Bench,
) -> None:
    revision = await bench.revision()
    sensor = await bench.part("BME280", RawPin(number="3", label="SDI", type="io"))
    resistor = await bench.part("4k7")
    await bench.line(revision, sensor, "U2")
    await bench.line(revision, resistor, "R1")
    await bench.net(revision, "SDA", "U2.SDI, R1.2")

    await bench.catalog.replace_pinout(
        CatalogWorkspaceId(BENCH),
        PartDefinitionId(sensor),
        (RawPin(number="1", label="GND", type="ground"),),
    )
    lines = (await bench.projects.get_bom(BENCH, revision)).bom.lines
    (resistor_line,) = [line for line in lines if line.content.part_id == resistor]
    await bench.projects.update_bom_line(
        BENCH, revision, resistor_line.id, NewBomLine(resistor, Designators.parse("R7"), None)
    )

    view = await bench.get_netlist(BENCH, revision)
    (net,) = view.netlist.nets
    states = {str(ref): view.resolution(ref).state for ref in net.content.pins}
    assert states == {
        "R1.2": ResolutionState.UNKNOWN_DESIGNATOR,
        "U2.3": ResolutionState.UNKNOWN_PIN,
    }


async def test_another_benchs_nets_designators_and_parts_are_unseen(bench: Bench) -> None:
    theirs = await bench.revision(OTHER)
    their_part = await bench.part(
        "BME280", RawPin(number="3", label="SDI", type="io"), workspace_id=OTHER
    )
    await bench.line(theirs, their_part, "U2", OTHER)
    await bench.net(theirs, "SDA", "U2.3", OTHER)
    mine = await bench.revision()

    view = await bench.get_netlist(BENCH, mine)
    with pytest.raises(UnknownDesignatorError):
        await bench.net(mine, "SDA", "U2.3")

    assert view.netlist.nets == ()
    assert view.parts == {}
