"""A build transition stays inside its workspace, over Postgres as `wiredex_app`.

Every read and write of a transition rides one session under one workspace setting, so
row-level security scopes projects', catalog's and inventory's rows alike (10-build-lifecycle
requirement 11.1). What that means at the edge: a revision of another workspace is not found
(11.3), and a unit or a location of another workspace is treated as one this workspace doesn't
hold (11.2). These run as the restricted role the API logs in with, the one the policies
apply to.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import uuid7

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from support.sql import row_counts
from wiredex.bootstrap.build import SqlBuildUnitOfWork
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
from wiredex.inventory.application.units import NewUnit, UnitReceipt
from wiredex.inventory.domain.values import LocationId, LocationName, Quantity
from wiredex.inventory.domain.values import PartId as InventoryPartId
from wiredex.inventory.domain.values import WorkspaceId as InventoryWorkspaceId
from wiredex.projects.api.router import ProjectsUseCases
from wiredex.projects.application.lifecycle import (
    BuildRevision,
    DismantleRevision,
    ReserveRevision,
)
from wiredex.projects.application.ports import NewBomLine
from wiredex.projects.domain.designators import Designators
from wiredex.projects.domain.errors import RevisionNotFoundError
from wiredex.projects.domain.lifecycle import UnknownLocationError, UnknownUnitError
from wiredex.projects.domain.project import ProjectDetails
from wiredex.projects.domain.values import (
    LocationId as ProjectsLocationId,
)
from wiredex.projects.domain.values import PartId, ProjectName, RevisionId, WorkspaceId
from wiredex.projects.domain.values import UnitId as ProjectsUnitId
from wiredex.projects.domain.values import WorkspaceId as ProjectsWorkspaceId
from wiredex.shared_kernel.infrastructure.clock import SystemClock
from wiredex.shared_kernel.infrastructure.ids import Uuid7Generator

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

MINE = WorkspaceId(uuid7())
THEIRS = WorkspaceId(uuid7())
TABLES = (
    "bom_designators, bom_lines, revisions, projects, units, stock_movements, stock_balances,"
    " stock_lots, short_code_counters, locations, pins, part_definitions,"
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
class Modules:
    catalog: CatalogUseCases
    inventory: InventoryUseCases
    projects: ProjectsUseCases
    reserve: ReserveRevision
    build: BuildRevision
    dismantle: DismantleRevision

    async def category(
        self, workspace: WorkspaceId, name: str, *, tracked: bool = False
    ) -> CategoryId:
        view = await self.catalog.create_category(
            CatalogWorkspaceId(workspace), NewCategory(CategoryName(name))
        )
        if tracked:
            await self.catalog.set_category_tracking(
                CatalogWorkspaceId(workspace), view.category.id, True
            )
        return view.category.id

    async def part(self, workspace: WorkspaceId, category: CategoryId, name: str) -> PartId:
        part = await self.catalog.define_part(
            CatalogWorkspaceId(workspace), NewPart(category, PartDetails(PartName(name)))
        )
        return PartId(part.id)

    async def location(self, workspace: WorkspaceId, name: str) -> LocationId:
        location = await self.inventory.create_location(
            InventoryWorkspaceId(workspace), NewLocation(LocationName(name))
        )
        return location.id

    async def receive(
        self, workspace: WorkspaceId, part: PartId, location: LocationId, quantity: int
    ) -> None:
        await self.inventory.receive_stock(
            InventoryWorkspaceId(workspace),
            Receipt(InventoryPartId(part), location, Quantity(quantity)),
        )

    async def receive_units(
        self, workspace: WorkspaceId, part: PartId, location: LocationId, count: int
    ) -> ProjectsUnitId:
        received = await self.inventory.receive_units(
            InventoryWorkspaceId(workspace),
            UnitReceipt(InventoryPartId(part), location, (NewUnit(),) * count),
        )
        return ProjectsUnitId(received.units[0].id)

    async def revision(self, workspace: WorkspaceId) -> RevisionId:
        view = await self.projects.create_project(
            workspace, ProjectDetails(ProjectName("Weather station"))
        )
        latest = view.revisions.latest
        assert latest is not None
        return latest.id

    async def line(
        self, workspace: WorkspaceId, revision: RevisionId, part: PartId, qty: int
    ) -> None:
        await self.projects.add_bom_line(
            workspace, revision, NewBomLine(part, Designators.none(), qty)
        )


@pytest.fixture
def modules(app: AsyncEngine) -> Modules:
    session_factory = create_session_factory(app)
    clock, ids = SystemClock(), Uuid7Generator()

    def build_unit_of_work(workspace_id: ProjectsWorkspaceId) -> SqlBuildUnitOfWork:
        return SqlBuildUnitOfWork(session_factory, workspace_id, clock, ids)

    return Modules(
        catalog_use_cases(session_factory),
        inventory_use_cases(session_factory),
        projects_use_cases(session_factory),
        ReserveRevision(build_unit_of_work),
        BuildRevision(build_unit_of_work),
        DismantleRevision(build_unit_of_work),
    )


async def test_a_transition_of_another_workspaces_revision_is_not_found(
    modules: Modules,
) -> None:
    # Requirement 11.3: their revision reads as 404, not 403.
    passives = await modules.category(THEIRS, "Passives")
    resistor = await modules.part(THEIRS, passives, "Resistor 10k")
    drawer = await modules.location(THEIRS, "Drawer 3")
    await modules.receive(THEIRS, resistor, drawer, 40)
    theirs = await modules.revision(THEIRS)
    await modules.line(THEIRS, theirs, resistor, 3)

    with pytest.raises(RevisionNotFoundError):
        await modules.reserve(MINE, theirs, [])


async def test_a_reserve_naming_another_workspaces_unit_is_unknown(
    modules: Modules, admin: AsyncEngine
) -> None:
    # Requirement 11.2: their board is a unit this workspace doesn't hold, so the reserve is
    # refused as unknown_unit and nothing is written.
    their_boards = await modules.category(THEIRS, "Boards", tracked=True)
    their_esp32 = await modules.part(THEIRS, their_boards, "ESP32 board")
    their_drawer = await modules.location(THEIRS, "Drawer")
    their_unit = await modules.receive_units(THEIRS, their_esp32, their_drawer, 1)

    boards = await modules.category(MINE, "Boards", tracked=True)
    esp32 = await modules.part(MINE, boards, "ESP32 board")
    drawer = await modules.location(MINE, "Drawer 3")
    await modules.receive_units(MINE, esp32, drawer, 1)
    revision = await modules.revision(MINE)
    await modules.line(MINE, revision, esp32, 1)
    before = await row_counts(admin)

    with pytest.raises(UnknownUnitError):
        await modules.reserve(MINE, revision, [their_unit])

    assert await row_counts(admin) == before


async def test_a_dismantle_into_another_workspaces_location_is_unknown(
    modules: Modules,
) -> None:
    # Requirement 11.2: their location is one this workspace doesn't hold, so the dismantle is
    # refused as unknown_location.
    their_drawer = await modules.location(THEIRS, "Their drawer")

    passives = await modules.category(MINE, "Passives")
    resistor = await modules.part(MINE, passives, "Resistor 10k")
    drawer = await modules.location(MINE, "Drawer 3")
    await modules.receive(MINE, resistor, drawer, 40)
    revision = await modules.revision(MINE)
    await modules.line(MINE, revision, resistor, 3)
    await modules.reserve(MINE, revision, [])
    await modules.build(MINE, revision)  # build it so it can be dismantled

    with pytest.raises(UnknownLocationError):
        await modules.dismantle(MINE, revision, ProjectsLocationId(their_drawer))
