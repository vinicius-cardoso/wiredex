"""`RevisionStock` over `SqlInventoryRepositories` against a real PostgreSQL (task 7).

`RevisionStock` is inventory's half of a build transition, and it runs on repositories another
module's unit of work owns (design decision 8). Here it runs on `SqlInventoryRepositories`
built on the session a `SqlInventoryUnitOfWork` opened and set the workspace on — the shape
`bootstrap/build.py` (task 12) will bind — so what only PostgreSQL can prove is proved: the
lock order and, above all, that a transition's reads and writes stay a fixed number of
statements whatever the number of lots it touches (requirement 14.3, decision 17). The unit
behaviour is `tests/inventory/test_revision_stock.py`'s over the fakes.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid7

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from support.identity import ManualClock, NewIds
from support.sql import counting
from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.settings import Environment, Settings
from wiredex.inventory.application.builds import LotTake, RevisionStock
from wiredex.inventory.domain.ledger import StockMovement
from wiredex.inventory.domain.location import Location
from wiredex.inventory.domain.lot import StockBalance, StockLot
from wiredex.inventory.domain.unit import Unit, UnitStatus
from wiredex.inventory.domain.values import (
    LocationId,
    LocationName,
    MovementKind,
    PartId,
    RevisionId,
    ShortCode,
    StockLotId,
    StockMovementId,
    UnitId,
    WorkspaceId,
)
from wiredex.inventory.infrastructure.unit_of_work import (
    SqlInventoryRepositories,
    SqlInventoryUnitOfWork,
)

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

NOW = datetime(2026, 9, 28, 10, tzinfo=UTC)
BENCH = WorkspaceId(uuid7())
INVENTORY_TABLES = (
    "units, stock_movements, stock_balances, stock_lots, short_code_counters, locations"
)


@pytest.fixture
async def engine(migrated_database_url: str) -> AsyncIterator[AsyncEngine]:
    settings = Settings(environment=Environment.TEST, database_url=SecretStr(migrated_database_url))
    engine = create_engine(settings)
    yield engine
    async with engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE {INVENTORY_TABLES} CASCADE"))
    await engine.dispose()


def inventory(engine: AsyncEngine, workspace_id: WorkspaceId = BENCH) -> SqlInventoryUnitOfWork:
    return SqlInventoryUnitOfWork(create_session_factory(engine), workspace_id)


def a_location(code: str, name: str) -> Location:
    return Location(LocationId(uuid7()), BENCH, None, ShortCode(code), LocationName(name), NOW)


def a_lot(part_id: PartId, location: Location) -> StockLot:
    return StockLot(StockLotId(uuid7()), BENCH, part_id, location.id, NOW)


def a_unit(part_id: PartId, lot: StockLot, code: str) -> Unit:
    return Unit(
        UnitId(uuid7()),
        BENCH,
        part_id,
        lot.id,
        ShortCode(code),
        None,
        None,
        UnitStatus.IN_STOCK,
        NOW,
    )


def a_stock(work: SqlInventoryUnitOfWork) -> RevisionStock:
    """`RevisionStock` over repositories on the unit of work's session (design decision 8).

    Built the way `bootstrap/build.py` will bind it: `SqlInventoryRepositories` on the session
    `SqlInventoryUnitOfWork` opened and set the workspace on, so the whole transition — the
    seed's own writes, the reserve's, the balances and the units — rides one transaction and
    one commit.
    """
    repositories = SqlInventoryRepositories(work.session, BENCH)
    return RevisionStock(repositories, BENCH, ManualClock(NOW), NewIds())


async def _received(work: SqlInventoryUnitOfWork, lot: StockLot, quantity: int) -> None:
    """A first receipt into a lot: one balance at version 1, the insert path of `put`."""
    movement = StockMovement(
        StockMovementId(uuid7()),
        BENCH,
        lot.id,
        MovementKind.RECEIVE,
        quantity,
        None,
        None,
        None,
        None,
        NOW,
    )
    await work.balances.put(StockBalance.opening(lot.id).apply(movement))


async def on_hand_reserved(engine: AsyncEngine, lot_id: StockLotId) -> tuple[int, int]:
    async with inventory(engine) as work:
        balance = await work.balances.get(lot_id)
    assert balance is not None
    return int(balance.on_hand), int(balance.reserved)


async def test_a_reserve_locks_units_then_balances_in_order_and_writes_one_row_per_lot(
    engine: AsyncEngine,
) -> None:
    # Two lots of one unit-tracked part, each with a board: the reserve locks the units by id,
    # then the balances by lot id, and writes one RESERVE per lot, its unit reserved (10, 14.3).
    part = PartId(uuid7())
    drawer = a_location("WX-L-0001", "Drawer")
    shelf = a_location("WX-L-0002", "Shelf")
    lot_one = a_lot(part, drawer)
    lot_two = a_lot(part, shelf)
    unit_one = a_unit(part, lot_one, "WX-U-0001")
    unit_two = a_unit(part, lot_two, "WX-U-0002")
    async with inventory(engine) as work:
        for location in (drawer, shelf):
            await work.locations.add(location)
        for lot, unit in ((lot_one, unit_one), (lot_two, unit_two)):
            await work.lots.add(lot)
            await _received(work, lot, 1)
            await work.units.add(unit)
        await work.commit()

    revision = RevisionId(uuid7())
    async with inventory(engine) as work:
        stock = a_stock(work)
        locked = await stock.available([part], [])
        # The lots come back in lot-id order, the lock order decision 10 fixes.
        assert [row.lot.id for row in locked.lots] == sorted([lot_one.id, lot_two.id])
        assert locked.changed is False
        await stock.reserve(
            locked,
            revision,
            [LotTake(lot_one.id, 1, (unit_one.id,)), LotTake(lot_two.id, 1, (unit_two.id,))],
        )
        await work.commit()

    assert await on_hand_reserved(engine, lot_one.id) == (1, 1)
    assert await on_hand_reserved(engine, lot_two.id) == (1, 1)
    async with inventory(engine) as work:
        for unit in (unit_one, unit_two):
            saved = await work.units.get(unit.id)
            assert saved is not None
            assert saved.status is UnitStatus.RESERVED


@pytest.mark.parametrize("lots", [1, 5])
async def test_available_costs_a_fixed_number_of_statements_whatever_the_lots(
    engine: AsyncEngine, lots: int
) -> None:
    # Requirement 14.3: `available` locks the units and the balances in a fixed number of
    # statements — never one per lot — whatever the number of lots a part sits in.
    part = PartId(uuid7())
    made: list[StockLot] = []
    async with inventory(engine) as work:
        for index in range(lots):
            location = a_location(f"WX-L-{index:04d}", f"Drawer {index}")
            await work.locations.add(location)
            lot = a_lot(part, location)
            await work.lots.add(lot)
            await _received(work, lot, 3)
            made.append(lot)
        await work.commit()

    async with inventory(engine) as work:
        stock = a_stock(work)
        with counting(engine) as statements:
            locked = await stock.available([part], [])

    assert [row.lot.id for row in locked.lots] == sorted(lot.id for lot in made)
    # A lock of the units, a lock of the balances, and the recount is skipped for a
    # loose-lot part: a small constant, not one statement per lot.
    assert len(statements) <= 3, statements


@pytest.mark.parametrize("lots", [1, 5])
async def test_a_reserve_writes_a_fixed_number_of_statements_per_lot_touched(
    engine: AsyncEngine, lots: int
) -> None:
    # Requirement 14.3, decision 17: each lot touched costs one balance read (its FOR UPDATE)
    # and one balance write (`put`, no SELECT first) plus the ledger insert — a fixed number
    # per lot, never a SELECT-then-write growing the count.
    part = PartId(uuid7())
    made: list[StockLot] = []
    async with inventory(engine) as work:
        for index in range(lots):
            location = a_location(f"WX-L-{index:04d}", f"Drawer {index}")
            await work.locations.add(location)
            lot = a_lot(part, location)
            await work.lots.add(lot)
            await _received(work, lot, 3)
            made.append(lot)
        await work.commit()

    revision = RevisionId(uuid7())
    async with inventory(engine) as work:
        stock = a_stock(work)
        locked = await stock.available([part], [])
        takes = [LotTake(lot.id, 1, ()) for lot in made]
        with counting(engine) as statements:
            await stock.reserve(locked, revision, takes)
        await work.commit()

    # Per lot: read the balance, append the movement, put the balance. No SELECT-to-decide the
    # insert vs update, so the count grows by a fixed amount per lot, not more.
    assert len(statements) <= 3 * lots, statements
    for lot in made:
        assert (await on_hand_reserved(engine, lot.id))[1] == 1


async def test_build_then_dismantle_returns_the_stock_to_the_chosen_location(
    engine: AsyncEngine,
) -> None:
    # A loose-lot part reserved, built, then dismantled into another location: the total on
    # hand comes back, sitting at the chosen location, its return lot created (6.2, 6.3).
    part = PartId(uuid7())
    drawer = a_location("WX-L-0001", "Drawer")
    lab = a_location("WX-L-0002", "Lab")
    lot = a_lot(part, drawer)
    async with inventory(engine) as work:
        await work.locations.add(drawer)
        await work.locations.add(lab)
        await work.lots.add(lot)
        await _received(work, lot, 10)
        await work.commit()

    revision = RevisionId(uuid7())
    async with inventory(engine) as work:
        stock = a_stock(work)
        locked = await stock.available([part], [])
        await stock.reserve(locked, revision, [LotTake(lot.id, 4, ())])
        await work.commit()
    async with inventory(engine) as work:
        await a_stock(work).consume(revision)
        await work.commit()
    async with inventory(engine) as work:
        await a_stock(work).return_to(revision, lab.id)
        await work.commit()

    drawer_on_hand, _ = await on_hand_reserved(engine, lot.id)
    async with inventory(engine) as work:
        return_lot = await work.lots.for_part_at(part, lab.id)
    assert return_lot is not None
    lab_on_hand, lab_reserved = await on_hand_reserved(engine, return_lot.id)
    assert drawer_on_hand + lab_on_hand == 10
    assert (lab_on_hand, lab_reserved) == (4, 0)


async def test_holdings_and_units_of_a_revision_each_cost_one_query(engine: AsyncEngine) -> None:
    # The reads a lifecycle answer folds from: the revision's sums and its units, one query
    # each whatever it holds (requirements 8.5, 3.11, 10.6).
    part = PartId(uuid7())
    drawer = a_location("WX-L-0001", "Drawer")
    lot = a_lot(part, drawer)
    unit = a_unit(part, lot, "WX-U-0001")
    async with inventory(engine) as work:
        await work.locations.add(drawer)
        await work.lots.add(lot)
        await _received(work, lot, 2)
        await work.units.add(unit)
        await work.commit()

    revision = RevisionId(uuid7())
    async with inventory(engine) as work:
        stock = a_stock(work)
        locked = await stock.available([part], [])
        await stock.reserve(locked, revision, [LotTake(lot.id, 1, (unit.id,))])
        await work.commit()

    async with inventory(engine) as work:
        stock = a_stock(work)
        with counting(engine) as held_statements:
            held = await stock.holdings(revision)
        with counting(engine) as unit_statements:
            rows = await stock.units_of(revision)

    assert {h.lot_id: h.quantity for h in held.reserved} == {lot.id: 1}
    assert len(held_statements) == 1, held_statements
    assert [row.unit.id for row in rows] == [unit.id]
    assert len(unit_statements) == 1, unit_statements
