"""Movements on one lot at the same moment, against Postgres: no effect may be lost (5.5).

Each movement locks its lot's balance for its transaction, so simultaneous movements take
turns: the balance ends where the ledger says, however many there were.
"""

import asyncio
from collections.abc import AsyncIterator
from uuid import uuid7

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from wiredex.bootstrap.catalog import catalog_use_cases
from wiredex.bootstrap.database import create_session_factory
from wiredex.bootstrap.inventory import inventory_use_cases
from wiredex.catalog.application.categories import NewCategory
from wiredex.catalog.application.parts import NewPart
from wiredex.catalog.domain.part import PartDetails
from wiredex.catalog.domain.values import CategoryName, PartName
from wiredex.catalog.domain.values import WorkspaceId as CatalogWorkspaceId
from wiredex.inventory.application.ports import Move, NewLocation, Receipt
from wiredex.inventory.application.units import NewUnit, UnitReceipt
from wiredex.inventory.domain.values import LocationName, PartId, Quantity, WorkspaceId

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

SIMULTANEOUS = 8


@pytest.fixture
async def engine(app_database_url: str) -> AsyncIterator[AsyncEngine]:
    # A pool as large as the burst, so every movement really runs in its own connection.
    engine = create_async_engine(app_database_url, pool_size=SIMULTANEOUS, max_overflow=0)
    yield engine
    await engine.dispose()


async def a_part_and_two_locations(
    engine: AsyncEngine, workspace: WorkspaceId
) -> tuple[PartId, NewLocation, NewLocation]:
    catalog = catalog_use_cases(create_session_factory(engine))
    bench = CatalogWorkspaceId(workspace)
    category = await catalog.create_category(bench, NewCategory(CategoryName("Resistors")))
    part = await catalog.define_part(
        bench, NewPart(category.category.id, PartDetails(PartName("Resistor 10k")))
    )
    return PartId(part.id), NewLocation(LocationName("Drawer A")), NewLocation(LocationName("B"))


async def a_tracked_board(engine: AsyncEngine, workspace: WorkspaceId) -> PartId:
    catalog = catalog_use_cases(create_session_factory(engine))
    bench = CatalogWorkspaceId(workspace)
    category = await catalog.create_category(bench, NewCategory(CategoryName("Dev boards")))
    board_category = category.category.id
    await catalog.set_category_tracking(bench, board_category, True)
    part = await catalog.define_part(bench, NewPart(board_category, PartDetails(PartName("ESP32"))))
    return PartId(part.id)


async def test_simultaneous_receipts_all_count(engine: AsyncEngine) -> None:
    workspace = WorkspaceId(uuid7())
    part, drawer, _ = await a_part_and_two_locations(engine, workspace)
    inventory = inventory_use_cases(create_session_factory(engine))
    location = await inventory.create_location(workspace, drawer)
    await inventory.receive_stock(workspace, Receipt(part, location.id, Quantity(1)))

    await asyncio.gather(
        *(
            inventory.receive_stock(workspace, Receipt(part, location.id, Quantity(1)))
            for _ in range(SIMULTANEOUS)
        )
    )

    stock = await inventory.part_stock(workspace, part)
    assert stock.total == SIMULTANEOUS + 1
    assert await ledger_total(engine, workspace) == SIMULTANEOUS + 1


async def test_opposite_simultaneous_moves_neither_deadlock_nor_lose_stock(
    engine: AsyncEngine,
) -> None:
    workspace = WorkspaceId(uuid7())
    part, first, second = await a_part_and_two_locations(engine, workspace)
    inventory = inventory_use_cases(create_session_factory(engine))
    a = await inventory.create_location(workspace, first)
    b = await inventory.create_location(workspace, second)
    await inventory.receive_stock(workspace, Receipt(part, a.id, Quantity(50)))
    await inventory.receive_stock(workspace, Receipt(part, b.id, Quantity(50)))

    await asyncio.gather(
        *(
            inventory.move_stock(
                workspace,
                Move(part, *((a.id, b.id) if turn % 2 else (b.id, a.id)), Quantity(1)),
            )
            for turn in range(SIMULTANEOUS)
        )
    )

    stock = await inventory.part_stock(workspace, part)
    assert sorted(int(row.on_hand) for row in stock.breakdown) == [50, 50]
    assert await ledger_total(engine, workspace) == 100


async def ledger_total(engine: AsyncEngine, workspace: WorkspaceId) -> int:
    """The sum of every movement, read under the workspace's row-level security."""
    async with engine.begin() as connection:
        await connection.execute(
            text("SELECT set_config('app.workspace_id', :w, true)"), {"w": str(workspace)}
        )
        total = await connection.scalar(
            text("SELECT coalesce(sum(change), 0) FROM stock_movements")
        )
    return int(total or 0)


async def test_the_ledger_cannot_be_rewritten(engine: AsyncEngine) -> None:
    # ADR 0002: a movement is never rewritten; the API's role may add movements, not edit them.
    workspace = WorkspaceId(uuid7())
    part, drawer, _ = await a_part_and_two_locations(engine, workspace)
    inventory = inventory_use_cases(create_session_factory(engine))
    location = await inventory.create_location(workspace, drawer)
    await inventory.receive_stock(workspace, Receipt(part, location.id, Quantity(5)))

    with pytest.raises(ProgrammingError, match="permission denied"):
        await rewrite_ledger(engine, workspace)

    assert await ledger_total(engine, workspace) == 5


async def rewrite_ledger(engine: AsyncEngine, workspace: WorkspaceId) -> None:
    """Try to edit the workspace's movements in place, as a bug might."""
    async with engine.begin() as connection:
        await connection.execute(
            text("SELECT set_config('app.workspace_id', :w, true)"), {"w": str(workspace)}
        )
        await connection.execute(text("UPDATE stock_movements SET change = 500"))


async def test_simultaneous_retires_of_one_unit_count_once(engine: AsyncEngine) -> None:
    # Each retire loads the unit locked, so the second one finds it retired and does nothing.
    workspace = WorkspaceId(uuid7())
    board = await a_tracked_board(engine, workspace)
    inventory = inventory_use_cases(create_session_factory(engine))
    drawer = await inventory.create_location(workspace, NewLocation(LocationName("Drawer A")))
    received = await inventory.receive_units(
        workspace, UnitReceipt(board, drawer.id, (NewUnit(), NewUnit()))
    )
    unit = received.units[0]

    await asyncio.gather(*(inventory.retire_unit(workspace, unit.id) for _ in range(SIMULTANEOUS)))

    stock = await inventory.part_stock(workspace, board)
    assert stock.total == 1
    assert await ledger_total(engine, workspace) == 1


async def test_simultaneous_moves_of_one_unit_move_it_once(engine: AsyncEngine) -> None:
    workspace = WorkspaceId(uuid7())
    board = await a_tracked_board(engine, workspace)
    inventory = inventory_use_cases(create_session_factory(engine))
    drawer = await inventory.create_location(workspace, NewLocation(LocationName("Drawer A")))
    box = await inventory.create_location(workspace, NewLocation(LocationName("Box")))
    received = await inventory.receive_units(
        workspace, UnitReceipt(board, drawer.id, (NewUnit(), NewUnit()))
    )
    unit = received.units[0]
    # The box already holds a board, so no move has to create its lot: creating one at the
    # same moment would collide on its own and hide the race.
    await inventory.receive_units(workspace, UnitReceipt(board, box.id, (NewUnit(),)))

    # The first move wins; the rest find the unit already in the box and are refused.
    outcomes = await asyncio.gather(
        *(inventory.move_unit(workspace, unit.id, box.id) for _ in range(SIMULTANEOUS)),
        return_exceptions=True,
    )

    assert sum(not isinstance(outcome, BaseException) for outcome in outcomes) == 1
    stock = await inventory.part_stock(workspace, board)
    assert sorted(int(row.on_hand) for row in stock.breakdown) == [1, 2]
