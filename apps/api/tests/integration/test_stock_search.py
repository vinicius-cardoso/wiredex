"""The parts list's stock filter over the real wiring: catalog's search asks inventory, through
`bootstrap/catalog.py`, which parts hold stock, in inventory's own transaction, and narrows
by that set in its own. A board in stock counts as its part's stock, as the list's column does.
"""

from collections.abc import AsyncIterator
from uuid import uuid7

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from wiredex.bootstrap.catalog import catalog_use_cases
from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.inventory import inventory_use_cases
from wiredex.bootstrap.settings import Environment, Settings
from wiredex.catalog.application.categories import NewCategory
from wiredex.catalog.application.parts import NewPart
from wiredex.catalog.application.search import PartSearch
from wiredex.catalog.domain.part import PartDetails
from wiredex.catalog.domain.search import StockState
from wiredex.catalog.domain.values import CategoryId, CategoryName, PartName
from wiredex.catalog.domain.values import WorkspaceId as CatalogWorkspaceId
from wiredex.inventory.application.ports import NewLocation, Receipt
from wiredex.inventory.application.units import NewUnit, UnitReceipt
from wiredex.inventory.domain.values import LocationName, PartId, Quantity, WorkspaceId

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

BENCH = WorkspaceId(uuid7())
TABLES = (
    "units, stock_movements, stock_balances, stock_lots, short_code_counters, locations,"
    " pins, part_definitions, attribute_definitions, categories"
)


@pytest.fixture
async def admin(migrated_database_url: str) -> AsyncIterator[AsyncEngine]:
    """The schema owner, which the policies don't apply to: it empties every workspace."""
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


async def test_the_stock_filter_reads_what_inventory_holds(app: AsyncEngine) -> None:
    sessions = create_session_factory(app)
    catalog, inventory = catalog_use_cases(sessions), inventory_use_cases(sessions)
    here = CatalogWorkspaceId(BENCH)
    resistors = await catalog.create_category(here, NewCategory(CategoryName("Resistors")))
    boards = await catalog.create_category(here, NewCategory(CategoryName("Boards")))
    await catalog.set_category_tracking(here, boards.category.id, True)

    async def a_part(category_id: CategoryId, name: str) -> PartId:
        part = await catalog.define_part(here, NewPart(category_id, PartDetails(PartName(name))))
        return PartId(part.id)

    held = await a_part(resistors.category.id, "R 4k7")
    await a_part(resistors.category.id, "R 10k")
    board = await a_part(boards.category.id, "ESP32-DevKitC")
    drawer = await inventory.create_location(BENCH, NewLocation(LocationName("Drawer 3")))
    await inventory.receive_stock(BENCH, Receipt(held, drawer.id, Quantity(25)))
    await inventory.receive_units(BENCH, UnitReceipt(board, drawer.id, (NewUnit(),)))

    in_stock = await catalog.search_parts(
        here, PartSearch(stock=StockState.IN_STOCK, sort="name", direction="asc")
    )
    out_of_stock = await catalog.search_parts(here, PartSearch(stock=StockState.OUT_OF_STOCK))

    assert [str(part.name) for part in in_stock.items] == ["ESP32-DevKitC", "R 4k7"]
    assert [str(part.name) for part in out_of_stock.items] == ["R 10k"]
