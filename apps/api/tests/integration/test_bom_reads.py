"""A BOM read over Postgres, as `wiredex_app`, through the use cases the routes are wired with.

The one read that touches three modules (design's Architecture): projects reads the revision
and its lines, then asks catalog about the parts and inventory about their stock, each in a
transaction of its own. What only the real wiring can show: that it costs nine statements
whatever the BOM's size (requirement 12.3), that another workspace's part is unknown (9.3),
and that the report follows the catalog and the stock as they stand at each read (6.7, 8.3).
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
from wiredex.catalog.application.parts import NewPart, PartRevision
from wiredex.catalog.domain.part import PartDetails
from wiredex.catalog.domain.values import CategoryId, CategoryName, PartDefinitionId, PartName
from wiredex.catalog.domain.values import WorkspaceId as CatalogWorkspaceId
from wiredex.inventory.api.router import InventoryUseCases
from wiredex.inventory.application.ports import NewLocation, Receipt
from wiredex.inventory.application.units import NewUnit, UnitReceipt
from wiredex.inventory.domain.values import LocationId, LocationName, Quantity
from wiredex.inventory.domain.values import PartId as InventoryPartId
from wiredex.inventory.domain.values import WorkspaceId as InventoryWorkspaceId
from wiredex.projects.api.router import ProjectsUseCases
from wiredex.projects.application.ports import NewBomLine
from wiredex.projects.domain.designators import Designators
from wiredex.projects.domain.errors import UnknownPartError
from wiredex.projects.domain.project import ProjectDetails
from wiredex.projects.domain.shortage import StockStatus
from wiredex.projects.domain.values import PartId, ProjectName, RevisionId, WorkspaceId

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

BENCH = WorkspaceId(uuid7())
OTHER = WorkspaceId(uuid7())
TABLES = (
    "bom_designators, bom_lines, revisions, projects, units, stock_movements, stock_balances,"
    " stock_lots, short_code_counters, locations, pins, part_definitions,"
    " attribute_definitions, categories"
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

    async def drawer(self) -> LocationId:
        location = await self.inventory.create_location(
            InventoryWorkspaceId(BENCH), NewLocation(LocationName("Drawer 3"))
        )
        return location.id

    async def revision(self) -> RevisionId:
        view = await self.projects.create_project(
            BENCH, ProjectDetails(ProjectName("Weather station"))
        )
        latest = view.revisions.latest
        assert latest is not None
        return latest.id

    async def line(
        self, revision: RevisionId, part: PartId, designators: str = "", quantity: int = 1
    ) -> None:
        typed = Designators.parse(designators)
        await self.projects.add_bom_line(
            BENCH, revision, NewBomLine(part, typed, None if typed else quantity)
        )


@pytest.fixture
def modules(app: AsyncEngine) -> Modules:
    session_factory = create_session_factory(app)
    return Modules(
        catalog_use_cases(session_factory),
        inventory_use_cases(session_factory),
        projects_use_cases(session_factory),
    )


@pytest.mark.parametrize(("lines", "parts"), [(1, 1), (40, 30)])
async def test_a_bom_read_costs_nine_statements_whatever_its_size(
    modules: Modules, app: AsyncEngine, lines: int, parts: int
) -> None:
    # Four in projects (the setting, the revision, the lines, their designators), three in
    # catalog (the setting, the parts, the tree) and two in inventory (the setting, the sum).
    passives = await modules.category("Passives")
    held = [await modules.part(passives, f"Resistor {n}") for n in range(parts)]
    drawer = await modules.drawer()
    await modules.inventory.receive_stock(
        InventoryWorkspaceId(BENCH), Receipt(InventoryPartId(held[0]), drawer, Quantity(5))
    )
    revision = await modules.revision()
    for n in range(lines):
        await modules.line(revision, held[n % parts], f"R{n + 1}")

    with counting(app) as statements:
        view = await modules.projects.get_bom(BENCH, revision)

    assert len(view.bom.lines) == lines
    assert len(view.report.parts) == parts
    assert len(statements) == 9, statements


async def test_a_line_naming_another_workspaces_part_is_refused_as_unknown(
    modules: Modules,
) -> None:
    # Requirement 9.3: row-level security and the catalog's filter leave it out alike.
    theirs = await modules.part(await modules.category("Passives", OTHER), "Resistor", OTHER)
    revision = await modules.revision()

    with pytest.raises(UnknownPartError):
        await modules.line(revision, theirs, "R1")

    assert (await modules.projects.get_bom(BENCH, revision)).bom.lines == ()


async def test_the_report_follows_a_rename_and_a_flag_change_at_the_next_read(
    modules: Modules,
) -> None:
    # Requirements 6.7 and 8.3: nothing is stored, so nothing needs refreshing.
    here = CatalogWorkspaceId(BENCH)
    consumables = await modules.category("Consumables")
    wire = await modules.part(consumables, "Wire")
    revision = await modules.revision()
    await modules.line(revision, wire, quantity=1)

    [before] = (await modules.projects.get_bom(BENCH, revision)).report.parts
    await modules.catalog.update_part(
        here, PartDefinitionId(wire), PartRevision(PartDetails(PartName("Hook-up wire 22 AWG")))
    )
    await modules.catalog.set_category_stocking(here, consumables, True)
    [after] = (await modules.projects.get_bom(BENCH, revision)).report.parts

    assert before.part is not None
    assert (before.part.name, before.status, before.short) == ("Wire", StockStatus.SHORT, 1)
    assert after.part is not None
    assert (after.part.name, after.status, after.short) == (
        "Hook-up wire 22 AWG",
        StockStatus.NOT_STOCKED,
        0,
    )


async def test_a_unit_tracked_parts_available_stock_is_its_in_stock_units(
    modules: Modules,
) -> None:
    # Requirement 6.3: three received and one retired leaves two in stock.
    boards = await modules.category("Boards")
    await modules.catalog.set_category_tracking(CatalogWorkspaceId(BENCH), boards, True)
    board = await modules.part(boards, "ESP32-DevKitC")
    drawer = await modules.drawer()
    received = await modules.inventory.receive_units(
        InventoryWorkspaceId(BENCH),
        UnitReceipt(InventoryPartId(board), drawer, (NewUnit(),) * 3),
    )
    await modules.inventory.retire_unit(InventoryWorkspaceId(BENCH), received.units[0].id)
    revision = await modules.revision()
    await modules.line(revision, board, "U1-U3")

    [part] = (await modules.projects.get_bom(BENCH, revision)).report.parts

    assert (part.available, part.short, part.status) == (2, 1, StockStatus.SHORT)
