"""A build transition over Postgres, as `wiredex_app`: one transaction across three modules.

`SqlBuildUnitOfWork` binds inventory's stock and catalog's parts to the session projects' unit
of work opened, so a revision's status, its movements, its balances and its units are written
in one transaction, under one workspace setting, and kept by one `commit()` (10-build-lifecycle
decision 8, requirement 11.1). Task 13 wires the transitions into `ProjectsUseCases` with their
routes; here the tests build them over `SqlBuildUnitOfWork` themselves.

What only the real wiring can show: that a reserve commits once and everything lands together
(requirement 1.3), that a refused transition leaves every table as it was (1.4), and that a
build then dismantle returns the stock to a chosen location (6.3), the round trip the fakes
can't roll back.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import uuid7

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from support.sql import committing, row_counts
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
    CancelReservation,
    DismantleRevision,
    GetLifecycle,
    ListPartHoldings,
    ReserveRevision,
)
from wiredex.projects.application.ports import NewBomLine
from wiredex.projects.domain.designators import Designators
from wiredex.projects.domain.lifecycle import ShortError
from wiredex.projects.domain.project import ProjectDetails
from wiredex.projects.domain.values import (
    LocationId as ProjectsLocationId,
)
from wiredex.projects.domain.values import (
    PartId,
    ProjectName,
    RevisionId,
    RevisionStatus,
    WorkspaceId,
)
from wiredex.projects.domain.values import WorkspaceId as ProjectsWorkspaceId
from wiredex.shared_kernel.infrastructure.clock import SystemClock
from wiredex.shared_kernel.infrastructure.ids import Uuid7Generator

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

BENCH = WorkspaceId(uuid7())
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
class Lifecycle:
    """The transitions and reads over `SqlBuildUnitOfWork`, as task 13 will wire them."""

    reserve: ReserveRevision
    cancel: CancelReservation
    build: BuildRevision
    dismantle: DismantleRevision
    get_lifecycle: GetLifecycle
    list_part_holdings: ListPartHoldings


@dataclass(frozen=True, slots=True)
class Modules:
    """The three modules' use cases over one engine, plus the build lifecycle over
    `SqlBuildUnitOfWork`."""

    catalog: CatalogUseCases
    inventory: InventoryUseCases
    projects: ProjectsUseCases
    lifecycle: Lifecycle

    async def category(self, name: str, *, tracked: bool = False) -> CategoryId:
        view = await self.catalog.create_category(
            CatalogWorkspaceId(BENCH), NewCategory(CategoryName(name))
        )
        if tracked:
            await self.catalog.set_category_tracking(
                CatalogWorkspaceId(BENCH), view.category.id, True
            )
        return view.category.id

    async def part(self, category: CategoryId, name: str) -> PartId:
        part = await self.catalog.define_part(
            CatalogWorkspaceId(BENCH), NewPart(category, PartDetails(PartName(name)))
        )
        return PartId(part.id)

    async def location(self, name: str) -> LocationId:
        location = await self.inventory.create_location(
            InventoryWorkspaceId(BENCH), NewLocation(LocationName(name))
        )
        return location.id

    async def receive(self, part: PartId, location: LocationId, quantity: int) -> None:
        await self.inventory.receive_stock(
            InventoryWorkspaceId(BENCH),
            Receipt(InventoryPartId(part), location, Quantity(quantity)),
        )

    async def receive_units(self, part: PartId, location: LocationId, count: int) -> None:
        await self.inventory.receive_units(
            InventoryWorkspaceId(BENCH),
            UnitReceipt(InventoryPartId(part), location, (NewUnit(),) * count),
        )

    async def revision(self) -> RevisionId:
        view = await self.projects.create_project(
            BENCH, ProjectDetails(ProjectName("Weather station"))
        )
        latest = view.revisions.latest
        assert latest is not None
        return latest.id

    async def line(self, revision: RevisionId, part: PartId, quantity: int) -> None:
        await self.projects.add_bom_line(
            BENCH, revision, NewBomLine(part, Designators.none(), quantity)
        )


@pytest.fixture
def modules(app: AsyncEngine) -> Modules:
    session_factory = create_session_factory(app)
    clock, ids = SystemClock(), Uuid7Generator()

    def build_unit_of_work(workspace_id: ProjectsWorkspaceId) -> SqlBuildUnitOfWork:
        return SqlBuildUnitOfWork(session_factory, workspace_id, clock, ids)

    lifecycle = Lifecycle(
        reserve=ReserveRevision(build_unit_of_work),
        cancel=CancelReservation(build_unit_of_work),
        build=BuildRevision(build_unit_of_work),
        dismantle=DismantleRevision(build_unit_of_work),
        get_lifecycle=GetLifecycle(build_unit_of_work),
        list_part_holdings=ListPartHoldings(build_unit_of_work),
    )
    return Modules(
        catalog_use_cases(session_factory),
        inventory_use_cases(session_factory),
        projects_use_cases(session_factory),
        lifecycle,
    )


async def a_reservable_bench(modules: Modules) -> tuple[RevisionId, PartId, PartId, LocationId]:
    """A draft *Weather station* whose BOM needs one ESP32 board and three 10k resistors, with
    the stock to cover it: one board as a unit, forty resistors loose."""
    boards = await modules.category("Boards", tracked=True)
    passives = await modules.category("Passives")
    esp32 = await modules.part(boards, "ESP32 board")
    resistor = await modules.part(passives, "Resistor 10k")
    drawer = await modules.location("Drawer 3")
    await modules.receive_units(esp32, drawer, 1)
    await modules.receive(resistor, drawer, 40)
    revision = await modules.revision()
    await modules.line(revision, esp32, 1)
    await modules.line(revision, resistor, 3)
    return revision, esp32, resistor, drawer


async def rows(admin: AsyncEngine, sql: str, **parameters: object) -> list[tuple[object, ...]]:
    async with admin.connect() as connection:
        result = await connection.execute(text(sql), parameters)
        return [tuple(row) for row in result]


async def test_a_reserve_commits_once_and_everything_lands_together(
    modules: Modules, app: AsyncEngine, admin: AsyncEngine
) -> None:
    # Requirement 1.3: the status, the RESERVE movements, the reserved balances and the
    # reserved unit are all written in one commit.
    revision, esp32, resistor, _ = await a_reservable_bench(modules)

    with committing(app) as commits:
        reserved = await modules.lifecycle.reserve(BENCH, revision, [])

    assert reserved.status is RevisionStatus.RESERVED
    assert len(commits) == 1
    # Two RESERVE rows, one per part's lot, each naming the revision.
    reserve_rows = await rows(
        admin,
        "SELECT count(*) FROM stock_movements WHERE kind = 'RESERVE' AND revision_id = :rev",
        rev=revision,
    )
    assert reserve_rows == [(2,)]
    # The board is reserved for the revision.
    assert await rows(
        admin,
        "SELECT status::text, revision_id FROM units WHERE part_id = :part",
        part=esp32,
    ) == [("reserved", revision)]
    # The resistor lot reserves three.
    assert await rows(
        admin,
        "SELECT b.reserved FROM stock_balances b JOIN stock_lots l ON l.id = b.lot_id"
        " WHERE l.part_id = :part",
        part=resistor,
    ) == [(3,)]


async def test_a_short_reserve_writes_nothing(modules: Modules, admin: AsyncEngine) -> None:
    # Requirement 1.4, 2.2: not enough resistors, so the reserve is refused and no row of it
    # is written — the status, the ledger, the balances and the units stay as they were.
    boards = await modules.category("Boards", tracked=True)
    passives = await modules.category("Passives")
    esp32 = await modules.part(boards, "ESP32 board")
    resistor = await modules.part(passives, "Resistor 10k")
    drawer = await modules.location("Drawer 3")
    await modules.receive_units(esp32, drawer, 1)
    await modules.receive(resistor, drawer, 1)  # short: needs three
    revision = await modules.revision()
    await modules.line(revision, esp32, 1)
    await modules.line(revision, resistor, 3)
    before = await row_counts(admin)

    with pytest.raises(ShortError):
        await modules.lifecycle.reserve(BENCH, revision, [])

    assert await row_counts(admin) == before
    status = await rows(admin, "SELECT status::text FROM revisions WHERE id = :rev", rev=revision)
    assert status == [("draft",)]


async def test_build_then_dismantle_returns_the_stock_to_a_chosen_location(
    modules: Modules, admin: AsyncEngine
) -> None:
    # Requirements 5.1, 6.3: building consumes the reservation; dismantling returns everything
    # to the chosen location, its return lot created.
    revision, esp32, resistor, _drawer = await a_reservable_bench(modules)
    lab = await modules.location("Lab")

    await modules.lifecycle.reserve(BENCH, revision, [])
    built = await modules.lifecycle.build(BENCH, revision)
    assert built.status is RevisionStatus.BUILT
    dismantled = await modules.lifecycle.dismantle(BENCH, revision, ProjectsLocationId(lab))
    assert dismantled.status is RevisionStatus.DISMANTLED

    # The resistor's total on hand is back to 40, split between the drawer and the lab.
    totals = await rows(
        admin,
        "SELECT loc.code, b.on_hand FROM stock_balances b JOIN stock_lots l ON l.id = b.lot_id"
        " JOIN locations loc ON loc.id = l.location_id WHERE l.part_id = :part ORDER BY loc.code",
        part=resistor,
    )
    assert sum(int(row[1]) for row in totals) == 40  # type: ignore[call-overload]
    # The board is back in stock at the lab, its revision link cleared.
    assert await rows(
        admin,
        "SELECT status::text, revision_id FROM units WHERE part_id = :part",
        part=esp32,
    ) == [("in_stock", None)]


async def test_a_cancel_leaves_every_balance_and_unit_as_it_started(
    modules: Modules, admin: AsyncEngine
) -> None:
    # Requirement 4.2: reserving then cancelling leaves the stock as it was.
    revision, esp32, resistor, _ = await a_reservable_bench(modules)
    before_units = await rows(
        admin, "SELECT status::text, revision_id FROM units WHERE part_id = :p", p=esp32
    )

    await modules.lifecycle.reserve(BENCH, revision, [])
    cancelled = await modules.lifecycle.cancel(BENCH, revision)

    assert cancelled.status is RevisionStatus.DRAFT
    assert (
        await rows(admin, "SELECT status::text, revision_id FROM units WHERE part_id = :p", p=esp32)
        == before_units
    )
    # No reserved stock left on the resistor lot.
    assert await rows(
        admin,
        "SELECT b.reserved FROM stock_balances b JOIN stock_lots l ON l.id = b.lot_id"
        " WHERE l.part_id = :p",
        p=resistor,
    ) == [(0,)]


async def test_the_lifecycle_and_holdings_reads_span_three_modules(modules: Modules) -> None:
    # Requirement 10.1, 10.4: a reserved revision's lifecycle answers each part it holds with
    # its facts (catalog) and its units (inventory), and the part-holdings read names it.
    revision, esp32, resistor, _ = await a_reservable_bench(modules)
    await modules.lifecycle.reserve(BENCH, revision, [])

    life = await modules.lifecycle.get_lifecycle(BENCH, revision)
    assert life.status is RevisionStatus.RESERVED
    by_part = {part.part_id: part for part in life.parts}
    esp32_part = by_part[esp32]
    assert esp32_part.facts is not None
    assert esp32_part.facts.name == "ESP32 board"
    assert [unit.code for unit in esp32_part.units]  # its reserved board

    holdings = await modules.lifecycle.list_part_holdings(BENCH, resistor)
    assert [holding.reserved for holding in holdings] == [3]
    assert holdings[0].revision.revision_id == revision
