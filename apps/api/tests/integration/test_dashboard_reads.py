"""The dashboard's projects reads over Postgres, as `wiredex_app`, through the use cases the
routes are wired with (18-dashboard).

The parts tied up in builds are folded from the ledger on the build unit of work's session, with
the revisions' refs and the catalog's facts read in the same transaction; the shortages read the
drafts and their BOMs, then ask the catalog and the stock in transactions of their own. What
only the real wiring can show: that the first read follows a reserve, a build, a dismantle and
a cancel as the ledger records them (requirement 1.4), that each costs the same statements
whatever the bench holds (6.1, 6.2), and that another bench's builds and drafts are never seen
(4.1).
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import uuid7

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from support.sql import counting
from wiredex.bootstrap.catalog import catalog_use_cases
from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.inventory import inventory_use_cases
from wiredex.bootstrap.projects import projects_use_cases
from wiredex.bootstrap.settings import Environment, Settings
from wiredex.catalog.api.router import CatalogUseCases
from wiredex.catalog.application.categories import NewCategory
from wiredex.catalog.application.parts import NewPart
from wiredex.catalog.domain.part import PartDetails
from wiredex.catalog.domain.values import CategoryId, CategoryName, PartName
from wiredex.catalog.domain.values import WorkspaceId as CatalogWorkspaceId
from wiredex.inventory.api.router import InventoryUseCases
from wiredex.inventory.application.ports import NewLocation, Receipt
from wiredex.inventory.domain.values import LocationId as InventoryLocationId
from wiredex.inventory.domain.values import LocationName, Quantity
from wiredex.inventory.domain.values import PartId as InventoryPartId
from wiredex.inventory.domain.values import WorkspaceId as InventoryWorkspaceId
from wiredex.projects.api.router import ProjectsUseCases
from wiredex.projects.application.dashboard import TiedUpParts
from wiredex.projects.application.ports import NewBomLine
from wiredex.projects.domain.designators import Designators
from wiredex.projects.domain.project import ProjectDetails
from wiredex.projects.domain.values import (
    LocationId,
    PartId,
    ProjectName,
    RevisionId,
    WorkspaceId,
)

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

BENCH = WorkspaceId(uuid7())
OTHER = WorkspaceId(uuid7())
TABLES = (
    "bom_designators, bom_lines, revisions, projects, units, stock_movements, stock_balances,"
    " stock_lots, short_code_counters, locations, pins, part_definitions,"
    " attribute_definitions, categories, history_entries, history_changes"
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
        await connection.execute(text(f"TRUNCATE {TABLES} CASCADE"))


@pytest.fixture
async def app(app_database_url: str) -> AsyncIterator[AsyncEngine]:
    settings = Settings(environment=Environment.TEST, database_url=SecretStr(app_database_url))
    engine = create_engine(settings)
    yield engine
    await engine.dispose()


@dataclass(frozen=True, slots=True)
class Modules:
    """The three modules' use cases over one engine, as `create_app` wires them."""

    catalog: CatalogUseCases
    inventory: InventoryUseCases
    projects: ProjectsUseCases

    async def category(self, name: str, workspace_id: WorkspaceId = BENCH) -> CategoryId:
        view = await self.catalog.create_category(
            CatalogWorkspaceId(workspace_id), NewCategory(CategoryName(name))
        )
        return view.category.id

    async def part(
        self, category: CategoryId, name: str, workspace_id: WorkspaceId = BENCH
    ) -> PartId:
        part = await self.catalog.define_part(
            CatalogWorkspaceId(workspace_id), NewPart(category, PartDetails(PartName(name)))
        )
        return PartId(part.id)

    async def drawer(self, workspace_id: WorkspaceId = BENCH) -> LocationId:
        location = await self.inventory.create_location(
            InventoryWorkspaceId(workspace_id), NewLocation(LocationName("Drawer 3"))
        )
        return LocationId(location.id)

    async def receive(
        self, part: PartId, drawer: LocationId, quantity: int, workspace_id: WorkspaceId = BENCH
    ) -> None:
        await self.inventory.receive_stock(
            InventoryWorkspaceId(workspace_id),
            Receipt(InventoryPartId(part), InventoryLocationId(drawer), Quantity(quantity)),
        )

    async def draft(
        self, name: str, lines: dict[PartId, int], workspace_id: WorkspaceId = BENCH
    ) -> RevisionId:
        view = await self.projects.create_project(workspace_id, ProjectDetails(ProjectName(name)))
        latest = view.revisions.latest
        assert latest is not None
        for part, quantity in lines.items():
            await self.projects.add_bom_line(
                workspace_id, latest.id, NewBomLine(part, Designators.none(), quantity)
            )
        return latest.id

    async def tied_up(self, workspace_id: WorkspaceId = BENCH) -> TiedUpParts:
        return await self.projects.list_tied_up_parts(workspace_id)


@pytest.fixture
def modules(app: AsyncEngine) -> Modules:
    session_factory = create_session_factory(app)
    return Modules(
        catalog_use_cases(session_factory),
        inventory_use_cases(session_factory),
        projects_use_cases(session_factory),
    )


def shares(tied_up: TiedUpParts) -> dict[PartId, list[tuple[str, int, int]]]:
    """Each part's revisions as (project, reserved, consumed), in the order answered."""
    return {
        part.part_id: [
            (str(view.revision.project_name), view.reserved, view.consumed)
            for view in part.revisions
        ]
        for part in tied_up.parts
    }


async def test_tied_up_parts_follow_a_reserve_a_build_a_dismantle_and_a_cancel(
    modules: Modules,
) -> None:
    # Requirements 1.1, 1.2 and 1.4, as the ledger records each transition.
    passives = await modules.category("Passives")
    resistor = await modules.part(passives, "Resistor 10k")
    capacitor = await modules.part(passives, "Capacitor 100n")
    drawer = await modules.drawer()
    await modules.receive(resistor, drawer, 40)
    await modules.receive(capacitor, drawer, 10)
    station = await modules.draft("Weather station", {resistor: 3, capacitor: 2})
    robot = await modules.draft("Robot", {resistor: 5})
    assert (await modules.tied_up()).parts == ()

    await modules.projects.reserve_revision(BENCH, station, [])
    await modules.projects.reserve_revision(BENCH, robot, [])
    assert shares(await modules.tied_up()) == {
        resistor: [("Robot", 5, 0), ("Weather station", 3, 0)],
        capacitor: [("Weather station", 2, 0)],
    }

    await modules.projects.build_revision(BENCH, robot)
    built = await modules.tied_up()
    assert [(part.part_id, part.reserved, part.consumed) for part in built.parts] == [
        (resistor, 3, 5),
        (capacitor, 2, 0),
    ]
    assert built.parts[0].facts is not None
    assert built.parts[0].facts.name == "Resistor 10k"

    await modules.projects.dismantle_revision(BENCH, robot, drawer)
    assert shares(await modules.tied_up()) == {
        resistor: [("Weather station", 3, 0)],
        capacitor: [("Weather station", 2, 0)],
    }

    await modules.projects.cancel_reservation(BENCH, station)
    assert (await modules.tied_up()).parts == ()


@pytest.mark.parametrize("projects", [1, 8])
async def test_tied_up_parts_cost_five_statements_whatever_the_bench_holds(
    modules: Modules, app: AsyncEngine, projects: int
) -> None:
    # Requirement 6.1: the setting, the grouped ledger read, the refs, and the catalog's parts
    # and tree, however many revisions, parts and lots.
    passives = await modules.category("Passives")
    drawer = await modules.drawer()
    for index in range(projects):
        part = await modules.part(passives, f"Resistor {index}")
        await modules.receive(part, drawer, 10)
        revision = await modules.draft(f"Project {index}", {part: index + 1})
        await modules.projects.reserve_revision(BENCH, revision, [])

    with counting(app) as statements:
        tied_up = await modules.tied_up()

    assert len(tied_up.parts) == projects
    assert len(statements) == 5, statements


async def test_another_benchs_builds_are_never_seen(modules: Modules) -> None:
    # Requirement 4.1: row-level security and the repositories' filters leave them out alike.
    passives = await modules.category("Passives", OTHER)
    resistor = await modules.part(passives, "Resistor 10k", OTHER)
    drawer = await modules.drawer(OTHER)
    await modules.receive(resistor, drawer, 10, OTHER)
    revision = await modules.draft("Weather station", {resistor: 3}, OTHER)
    await modules.projects.reserve_revision(OTHER, revision, [])

    assert [part.part_id for part in (await modules.tied_up(OTHER)).parts] == [resistor]
    assert (await modules.tied_up(BENCH)).parts == ()


@pytest.mark.parametrize(("drafts", "lines"), [(1, 1), (6, 5)])
async def test_shortages_cost_nine_statements_whatever_the_drafts_and_lines(
    modules: Modules, app: AsyncEngine, drafts: int, lines: int
) -> None:
    # Requirement 6.2: four in projects (the setting, the drafts, their lines, their
    # designators), three in catalog (the setting, the parts, the tree) and two in inventory
    # (the setting, the sum), each module's transaction after the one before closed.
    passives = await modules.category("Passives")
    parts = [await modules.part(passives, f"Resistor {index}") for index in range(lines)]
    drawer = await modules.drawer()
    await modules.receive(parts[0], drawer, 1)
    for index in range(drafts):
        await modules.draft(f"Project {index}", dict.fromkeys(parts, 2))

    with counting(app) as statements:
        short = await modules.projects.list_short_revisions(BENCH)

    assert len(short.revisions) == drafts
    assert len(statements) == 9, statements


async def test_shortages_leave_out_covered_reserved_and_trashed_drafts(modules: Modules) -> None:
    # Requirements 2.1, 2.2 and 2.4: only the draft short of the sensor is answered, with the
    # sensor alone among its parts.
    passives = await modules.category("Passives")
    resistor = await modules.part(passives, "Resistor 10k")
    sensor = await modules.part(passives, "BME280")
    drawer = await modules.drawer()
    await modules.receive(resistor, drawer, 10)
    await modules.draft("Covered", {resistor: 3})
    station = await modules.draft("Weather station", {resistor: 3, sensor: 1})
    reserved = await modules.draft("Reserved", {resistor: 2})
    await modules.projects.reserve_revision(BENCH, reserved, [])
    robot = await modules.projects.create_project(BENCH, ProjectDetails(ProjectName("Robot")))
    robot_draft = robot.revisions.latest
    assert robot_draft is not None
    await modules.projects.add_bom_line(
        BENCH, robot_draft.id, NewBomLine(sensor, Designators.none(), 2)
    )
    await modules.projects.delete_project(BENCH, robot.project.id)

    short = await modules.projects.list_short_revisions(BENCH)

    [found] = short.revisions
    assert found.revision.revision_id == station
    assert [
        (part.part_id, part.need.quantity, part.available, part.short) for part in found.missing
    ] == [(sensor, 1, 0, 1)]


async def test_another_benchs_shortages_are_never_seen(modules: Modules) -> None:
    # Requirement 4.1.
    passives = await modules.category("Passives", OTHER)
    sensor = await modules.part(passives, "BME280", OTHER)
    await modules.draft("Weather station", {sensor: 1}, OTHER)

    assert len((await modules.projects.list_short_revisions(OTHER)).revisions) == 1
    assert (await modules.projects.list_short_revisions(BENCH)).revisions == ()
