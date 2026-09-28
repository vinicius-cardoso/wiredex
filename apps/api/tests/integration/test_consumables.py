"""Consumables over Postgres, as `wiredex_app`, through the use cases the routes are wired with.

A part whose category resolves not stocked is never received, as a lot or as units, while
stock it held before the flag was set keeps working (09's decision 4). The flag is asked of
catalog through `bootstrap/parts.py` at every receipt, over the real recursive tree, and
setting it, or moving the category, rewrites nothing inventory holds (09's requirement 1.6).
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import uuid7

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from support.sql import row_counts
from wiredex.bootstrap.catalog import catalog_use_cases
from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.inventory import inventory_use_cases
from wiredex.bootstrap.settings import Environment, Settings
from wiredex.catalog.api.router import CatalogUseCases
from wiredex.catalog.application.categories import NewCategory
from wiredex.catalog.application.parts import NewPart
from wiredex.catalog.domain.part import PartDetails
from wiredex.catalog.domain.values import CategoryId, CategoryName, PartName
from wiredex.catalog.domain.values import WorkspaceId as CatalogWorkspaceId
from wiredex.inventory.api.router import InventoryUseCases
from wiredex.inventory.application.ports import Adjustment, Move, NewLocation, Receipt
from wiredex.inventory.application.units import NewUnit, UnitReceipt
from wiredex.inventory.domain.errors import NotStockedError
from wiredex.inventory.domain.location import Location
from wiredex.inventory.domain.values import (
    LocationName,
    MovementReason,
    PartId,
    Quantity,
    WorkspaceId,
)

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

BENCH = WorkspaceId(uuid7())
TABLES = (
    "units, stock_movements, stock_balances, stock_lots, short_code_counters, locations,"
    " pins, part_definitions, attribute_definitions, categories"
)
# Everything inventory holds, in an order that doesn't depend on how rows were written.
STOCK = {
    "stock_lots": "SELECT id, part_id, location_id FROM stock_lots ORDER BY id",
    "stock_balances": "SELECT lot_id, on_hand, reserved, available, version"
    " FROM stock_balances ORDER BY lot_id",
    "stock_movements": "SELECT id, lot_id, kind::text, change FROM stock_movements ORDER BY id",
    "units": "SELECT id, lot_id, code, status::text FROM units ORDER BY id",
}


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
class Bench:
    """*Consumables → Wire* holding a wire, a unit-tracked *Boards* holding a board, a
    *Parts box* root for a move, and two locations."""

    catalog: CatalogUseCases
    inventory: InventoryUseCases
    consumables: CategoryId
    boards: CategoryId
    parts_box: CategoryId
    wire: PartId
    board: PartId
    drawer: Location
    shelf: Location


@pytest.fixture
async def bench(app: AsyncEngine) -> Bench:
    session_factory = create_session_factory(app)
    catalog, inventory = catalog_use_cases(session_factory), inventory_use_cases(session_factory)
    here = CatalogWorkspaceId(BENCH)
    consumables = await catalog.create_category(here, NewCategory(CategoryName("Consumables")))
    wire_category = await catalog.create_category(
        here, NewCategory(CategoryName("Wire"), consumables.category.id)
    )
    boards = await catalog.create_category(here, NewCategory(CategoryName("Boards")))
    await catalog.set_category_tracking(here, boards.category.id, True)
    parts_box = await catalog.create_category(here, NewCategory(CategoryName("Parts box")))
    wire = await catalog.define_part(
        here, NewPart(wire_category.category.id, PartDetails(PartName("Hook-up wire 22 AWG")))
    )
    board = await catalog.define_part(
        here, NewPart(boards.category.id, PartDetails(PartName("ESP32-DevKitC")))
    )
    drawer = await inventory.create_location(BENCH, NewLocation(LocationName("Drawer 3")))
    shelf = await inventory.create_location(BENCH, NewLocation(LocationName("Shelf")))
    return Bench(
        catalog,
        inventory,
        consumables.category.id,
        boards.category.id,
        parts_box.category.id,
        PartId(wire.id),
        PartId(board.id),
        drawer,
        shelf,
    )


async def stock_rows(owner: AsyncEngine) -> dict[str, list[tuple[object, ...]]]:
    async with owner.connect() as connection:
        return {
            table: [tuple(row) for row in await connection.execute(text(sql))]
            for table, sql in STOCK.items()
        }


async def not_stocked(bench: Bench, category: CategoryId) -> None:
    await bench.catalog.set_category_stocking(CatalogWorkspaceId(BENCH), category, True)


async def test_receipts_of_a_not_stocked_categorys_parts_are_refused(
    bench: Bench, admin: AsyncEngine
) -> None:
    # 09's requirements 2.1 and 2.4: the wire inherits the flag from Consumables, and the
    # board, tracked and not stocked, is refused as not stocked too.
    await not_stocked(bench, bench.consumables)
    await not_stocked(bench, bench.boards)
    before = await row_counts(admin)

    with pytest.raises(NotStockedError):
        await bench.inventory.receive_stock(
            BENCH, Receipt(bench.wire, bench.drawer.id, Quantity(3))
        )
    with pytest.raises(NotStockedError):
        await bench.inventory.receive_units(
            BENCH, UnitReceipt(bench.board, bench.drawer.id, (NewUnit(),))
        )
    with pytest.raises(NotStockedError):
        await bench.inventory.adjust_stock(
            BENCH, Adjustment(bench.wire, bench.drawer.id, Quantity(3), MovementReason.RECOUNT)
        )

    assert await row_counts(admin) == before


async def test_a_lot_held_before_the_flag_is_still_recounted_and_moved(bench: Bench) -> None:
    # 09's requirement 2.3.
    await bench.inventory.receive_stock(BENCH, Receipt(bench.wire, bench.drawer.id, Quantity(10)))
    await not_stocked(bench, bench.consumables)

    recounted = await bench.inventory.adjust_stock(
        BENCH, Adjustment(bench.wire, bench.drawer.id, Quantity(8), MovementReason.RECOUNT)
    )
    source, dest = await bench.inventory.move_stock(
        BENCH, Move(bench.wire, bench.drawer.id, bench.shelf.id, Quantity(3))
    )

    assert int(recounted.on_hand) == 8
    assert (int(source.on_hand), int(dest.on_hand)) == (5, 3)


async def test_setting_the_flag_and_moving_the_category_rewrite_no_stock(
    bench: Bench, admin: AsyncEngine
) -> None:
    # 09's requirement 1.6: a lot, its movements and a board's units are left exactly as
    # they were, whichever way the flags resolve afterwards.
    here = CatalogWorkspaceId(BENCH)
    await bench.inventory.receive_stock(BENCH, Receipt(bench.wire, bench.drawer.id, Quantity(10)))
    await bench.inventory.receive_units(
        BENCH, UnitReceipt(bench.board, bench.drawer.id, (NewUnit(), NewUnit()))
    )
    before = await stock_rows(admin)

    await not_stocked(bench, bench.consumables)
    await not_stocked(bench, bench.boards)
    await bench.catalog.move_category(here, bench.boards, bench.parts_box)
    await bench.catalog.set_category_stocking(here, bench.consumables, None)

    assert await stock_rows(admin) == before
    assert before["units"]
    assert before["stock_movements"]
