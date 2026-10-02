"""The whole search over PostgreSQL, as `wiredex_app`, through the use cases the routes are wired
with (19-command-palette).

Six sources, each its module's own transaction, one after the other: what only the real wiring
can show is that the hits carry what each module answers (a part's maker and number, a unit's
part, a project's tags, a firmware's target, a location's code), and that the search costs the
same statements however many records match (requirement 6.1).
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID, uuid7

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from support.sql import counting
from wiredex.bootstrap.catalog import catalog_use_cases
from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.firmware import firmware_use_cases
from wiredex.bootstrap.inventory import inventory_use_cases
from wiredex.bootstrap.projects import projects_use_cases
from wiredex.bootstrap.search import search_use_cases
from wiredex.bootstrap.settings import Environment, Settings
from wiredex.catalog.api.router import CatalogUseCases
from wiredex.catalog.application.categories import NewCategory
from wiredex.catalog.application.parts import NewPart
from wiredex.catalog.domain.part import PartDetails
from wiredex.catalog.domain.values import CategoryId, CategoryName, Manufacturer, Mpn, PartName
from wiredex.catalog.domain.values import WorkspaceId as CatalogWorkspaceId
from wiredex.firmware.domain.firmware import FirmwareDetails
from wiredex.firmware.domain.values import BoardTarget, FirmwareName, Framework
from wiredex.firmware.domain.values import WorkspaceId as FirmwareWorkspaceId
from wiredex.inventory.api.router import InventoryUseCases
from wiredex.inventory.application.ports import NewLocation
from wiredex.inventory.application.units import NewUnit, UnitReceipt
from wiredex.inventory.domain.values import LocationId, LocationName, Serial
from wiredex.inventory.domain.values import PartId as InventoryPartId
from wiredex.inventory.domain.values import WorkspaceId as InventoryWorkspaceId
from wiredex.projects.domain.project import ProjectDetails
from wiredex.projects.domain.values import ProjectName, Tags
from wiredex.projects.domain.values import WorkspaceId as ProjectsWorkspaceId
from wiredex.search.api.router import SearchUseCases
from wiredex.search.domain.search import SearchKind, SearchResults, SearchText
from wiredex.search.domain.values import WorkspaceId

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

BENCH = uuid7()
TABLES = (
    "firmware_revisions, source_files, firmware_versions, firmware, bom_designators, bom_lines,"
    " revisions, projects, units, stock_movements, stock_balances, stock_lots,"
    " short_code_counters, locations, pins, part_definitions, attribute_definitions, categories,"
    " history_entries, history_changes"
)


@pytest.fixture
async def admin(migrated_database_url: str) -> AsyncIterator[AsyncEngine]:
    """The schema owner, which the policies don't apply to: it sees every bench."""
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
class Bench:
    """Every module's use cases over one engine, as `create_app` wires them, and the search."""

    catalog: CatalogUseCases
    inventory: InventoryUseCases
    search: SearchUseCases
    app: AsyncEngine

    async def category(self, name: str, *, tracked: bool = False) -> CategoryId:
        view = await self.catalog.create_category(
            CatalogWorkspaceId(BENCH), NewCategory(CategoryName(name))
        )
        if tracked:
            await self.catalog.set_category_tracking(
                CatalogWorkspaceId(BENCH), view.category.id, True
            )
        return view.category.id

    async def part(self, category: CategoryId, name: str, mpn: str | None = None) -> UUID:
        details = PartDetails(
            PartName(name),
            None if mpn is None else Manufacturer("Bosch"),
            None if mpn is None else Mpn(mpn),
        )
        part = await self.catalog.define_part(CatalogWorkspaceId(BENCH), NewPart(category, details))
        return part.id

    async def location(self, name: str) -> LocationId:
        location = await self.inventory.create_location(
            InventoryWorkspaceId(BENCH), NewLocation(LocationName(name))
        )
        return location.id

    async def units(self, part: UUID, location: LocationId, *serials: str) -> None:
        await self.inventory.receive_units(
            InventoryWorkspaceId(BENCH),
            UnitReceipt(
                InventoryPartId(part),
                location,
                tuple(NewUnit(serial=Serial(serial)) for serial in serials),
            ),
        )

    async def project(self, name: str, *tags: str) -> None:
        await projects_use_cases(create_session_factory(self.app)).create_project(
            ProjectsWorkspaceId(BENCH), ProjectDetails(ProjectName(name), tags=Tags.of(tags))
        )

    async def firmware(self, name: str, target: str) -> None:
        await firmware_use_cases(create_session_factory(self.app)).create_firmware(
            FirmwareWorkspaceId(BENCH),
            FirmwareDetails(FirmwareName(name), BoardTarget(target), Framework.ARDUINO),
            None,
        )

    async def find(self, typed: str, limit: int = 5) -> SearchResults:
        return await self.search.search_workspace(WorkspaceId(BENCH), SearchText.of(typed), limit)


@pytest.fixture
def bench(app: AsyncEngine) -> Bench:
    session_factory = create_session_factory(app)
    return Bench(
        catalog_use_cases(session_factory),
        inventory_use_cases(session_factory),
        search_use_cases(session_factory),
        app,
    )


def titled(found: SearchResults) -> list[tuple[SearchKind, list[tuple[str, str | None]]]]:
    return [(one.kind, [(hit.title, hit.detail) for hit in one.hits]) for one in found.groups]


async def test_every_kind_answers_its_hits_with_their_details(bench: Bench) -> None:
    # Requirements 1.1 to 1.3: one record of each kind holds "sensor".
    sensors = await bench.category("Sensors", tracked=True)
    board = await bench.part(sensors, "Weather board", mpn="BME280-SENSOR")
    shelf = await bench.location("Sensor shelf")
    await bench.units(board, shelf, "SENSOR-0001")
    await bench.project("Sensor station", "esp32", "i2c")
    await bench.firmware("Sensor logger", "esp32:esp32:esp32")

    found = await bench.find("sensor")

    assert titled(found) == [
        (SearchKind.PART, [("Weather board", "Bosch · BME280-SENSOR")]),
        (SearchKind.UNIT, [("WX-U-0001", "Weather board")]),
        (SearchKind.PROJECT, [("Sensor station", "esp32, i2c")]),
        (SearchKind.FIRMWARE, [("Sensor logger", "esp32:esp32:esp32")]),
        (SearchKind.CATEGORY, [("Sensors", None)]),
        (SearchKind.LOCATION, [("Sensor shelf", "WX-L-0001")]),
    ]
    assert all(not one.more for one in found.groups)


@pytest.mark.parametrize("records", [1, 7])
async def test_a_search_costs_fifteen_statements_whatever_matches(
    bench: Bench, app: AsyncEngine, records: int
) -> None:
    # Requirement 6.1: a setting and a find per module's transaction, six of them, and the
    # units' parts described once in catalog's own (a setting, the parts, the tree).
    sensors = await bench.category("Sensors", tracked=True)
    shelf = await bench.location("Sensor shelf")
    for index in range(records):
        part = await bench.part(sensors, f"Sensor {index}")
        await bench.units(part, shelf, f"SENSOR-{index}")
        await bench.project(f"Sensor station {index}")
        await bench.firmware(f"Sensor logger {index}", "esp32:esp32:esp32")

    with counting(app) as statements:
        found = await bench.find("sensor")

    assert [one.kind for one in found.groups] == list(SearchKind)
    assert [one.more for one in found.groups][:4] == [records > 5] * 4
    assert len(statements) == 15, statements


async def test_no_unit_matching_asks_the_catalog_nothing_more(
    bench: Bench, app: AsyncEngine
) -> None:
    await bench.project("Sensor station")

    with counting(app) as statements:
        found = await bench.find("sensor")

    assert [one.kind for one in found.groups] == [SearchKind.PROJECT]
    assert len(statements) == 12, statements
