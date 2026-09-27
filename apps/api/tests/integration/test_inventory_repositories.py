"""The inventory repositories against a real PostgreSQL: the tree, the indexes, the checks.

What can only be checked here is what the database does: one recursive query for a whole
ancestor chain, the trigram index answering a code search, the balance CHECKs refusing a bad
row, the optimistic-lock retry on `version`, and per-part totals in one grouped query.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid7

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from support.sql import counting
from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.settings import Environment, Settings
from wiredex.inventory.domain.ledger import StockMovement
from wiredex.inventory.domain.location import Location
from wiredex.inventory.domain.lot import StockBalance, StockLot
from wiredex.inventory.domain.values import (
    LocationId,
    LocationName,
    MovementKind,
    PartId,
    Quantity,
    ShortCode,
    StockLotId,
    StockMovementId,
    WorkspaceId,
)
from wiredex.inventory.infrastructure.unit_of_work import SqlInventoryUnitOfWork

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

NOW = datetime(2026, 9, 26, 10, tzinfo=UTC)
BENCH = WorkspaceId(uuid7())
INVENTORY_TABLES = "stock_movements, stock_balances, stock_lots, short_code_counters, locations"


@pytest.fixture
async def engine(migrated_database_url: str) -> AsyncIterator[AsyncEngine]:
    # The engine the API builds, so its session factory and JSON match production.
    settings = Settings(environment=Environment.TEST, database_url=SecretStr(migrated_database_url))
    engine = create_engine(settings)
    yield engine
    async with engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE {INVENTORY_TABLES} CASCADE"))
    await engine.dispose()


def inventory(engine: AsyncEngine, workspace_id: WorkspaceId = BENCH) -> SqlInventoryUnitOfWork:
    return SqlInventoryUnitOfWork(create_session_factory(engine), workspace_id)


def a_location(code: str, name: str, parent: Location | None = None) -> Location:
    return Location(
        LocationId(uuid7()),
        BENCH,
        None if parent is None else parent.id,
        ShortCode(code),
        LocationName(name),
        NOW,
    )


def a_lot(part_id: PartId, location: Location) -> StockLot:
    return StockLot(StockLotId(uuid7()), BENCH, part_id, location.id, NOW)


def a_movement(lot: StockLot, kind: MovementKind, change: int, at: datetime = NOW) -> StockMovement:
    return StockMovement(
        StockMovementId(uuid7()),
        BENCH,
        lot.id,
        kind,
        change,
        None,
        None,
        None,
        None,
        at,
    )


async def test_the_unit_of_work_binds_the_inventory_repositories(engine: AsyncEngine) -> None:
    # Every repository the port promises is bound and answers inside the `async with`. The
    # binding is checked behaviourally rather than by a port-typed assignment: `Ledger.all` is
    # declared a coroutine returning an iterator yet implemented — like the in-memory fake — as
    # an async generator, the shape `RebuildBalances`'s `async for` needs, so a structural
    # annotation would flag a mismatch the whole module deliberately lives with.
    async with inventory(engine) as work:
        assert await work.locations.all() == []
        assert await work.lots.get(StockLotId(uuid7())) is None
        assert await work.balances.totals_by_part([]) == {}
        assert await work.balances.get(StockLotId(uuid7())) is None
        assert [movement async for movement in work.ledger.all()] == []


async def test_the_ancestor_chain_comes_root_first_in_one_query(engine: AsyncEngine) -> None:
    lab = a_location("WX-L-0001", "Lab")
    cabinet = a_location("WX-L-0002", "Cabinet", lab)
    drawer = a_location("WX-L-0003", "Drawer 3", cabinet)
    async with inventory(engine) as work:
        for location in (lab, cabinet, drawer):
            await work.locations.add(location)
        await work.commit()

    async with inventory(engine) as work:
        with counting(engine) as statements:
            chain = await work.locations.ancestors(drawer.id)

    assert [str(location.name) for location in chain] == ["Lab", "Cabinet"]
    assert len(statements) == 1, statements


async def test_a_root_has_no_ancestors(engine: AsyncEngine) -> None:
    lab = a_location("WX-L-0001", "Lab")
    async with inventory(engine) as work:
        await work.locations.add(lab)
        await work.commit()

    async with inventory(engine) as work:
        assert await work.locations.ancestors(lab.id) == []


async def test_a_code_is_found_by_a_case_insensitive_substring(engine: AsyncEngine) -> None:
    # The trigram GIN index on `code`: a search matches a substring, ignoring case, and the
    # other codes stay out (design's Short codes).
    lab = a_location("WX-L-0007", "Lab")
    drawer = a_location("WX-L-0042", "Drawer 3")
    async with inventory(engine) as work:
        await work.locations.add(lab)
        await work.locations.add(drawer)
        await work.commit()

    async with inventory(engine) as work:
        by_tail = await work.locations.search("0007")
        lower = await work.locations.search("wx-l-0042")
        none = await work.locations.search("9999")

    assert [str(location.code) for location in by_tail] == ["WX-L-0007"]
    assert [str(location.code) for location in lower] == ["WX-L-0042"]
    assert none == []


async def test_has_lots_sees_a_lot_in_the_location(engine: AsyncEngine) -> None:
    lab = a_location("WX-L-0001", "Lab")
    empty = a_location("WX-L-0002", "Empty")
    part = PartId(uuid7())
    async with inventory(engine) as work:
        await work.locations.add(lab)
        await work.locations.add(empty)
        await work.lots.add(a_lot(part, lab))
        await work.commit()

    async with inventory(engine) as work:
        assert await work.locations.has_lots(lab.id) is True
        assert await work.locations.has_lots(empty.id) is False


async def test_a_lot_is_found_by_its_part_and_location(engine: AsyncEngine) -> None:
    lab = a_location("WX-L-0001", "Lab")
    part = PartId(uuid7())
    lot = a_lot(part, lab)
    async with inventory(engine) as work:
        await work.locations.add(lab)
        await work.lots.add(lot)
        await work.commit()

    async with inventory(engine) as work:
        found = await work.lots.for_part_at(part, lab.id)
        absent = await work.lots.for_part_at(PartId(uuid7()), lab.id)

    assert found is not None
    assert found.id == lot.id
    assert absent is None


async def test_the_ledger_returns_a_lots_movements_in_order(engine: AsyncEngine) -> None:
    lab = a_location("WX-L-0001", "Lab")
    part = PartId(uuid7())
    lot = a_lot(part, lab)
    first = a_movement(lot, MovementKind.RECEIVE, 100, NOW)
    second = a_movement(lot, MovementKind.ADJUST, -10, NOW + timedelta(minutes=1))
    async with inventory(engine) as work:
        await work.locations.add(lab)
        await work.lots.add(lot)
        await work.ledger.append(second)
        await work.ledger.append(first)
        await work.commit()

    async with inventory(engine) as work:
        movements = await work.ledger.movements_of(lot.id)
        streamed = [movement.id async for movement in work.ledger.all()]

    assert [movement.change for movement in movements] == [100, -10]
    assert streamed == [first.id, second.id]


async def test_a_balance_below_zero_is_refused_by_the_check(engine: AsyncEngine) -> None:
    # The CHECK `on_hand >= 0`: even a bug that wrote a negative on_hand is rejected.
    lab = a_location("WX-L-0001", "Lab")
    part = PartId(uuid7())
    lot = a_lot(part, lab)
    async with inventory(engine) as work:
        await work.locations.add(lab)
        await work.lots.add(lot)
        await work.commit()

    async with inventory(engine) as work:
        with pytest.raises(IntegrityError, match="ck_stock_balances_on_hand_non_negative"):
            await work.session.execute(
                text(
                    "INSERT INTO stock_balances"
                    " (lot_id, workspace_id, on_hand, reserved, available, version)"
                    " VALUES (:lot, :ws, -1, 0, -1, 0)"
                ),
                {"lot": str(lot.id), "ws": str(BENCH)},
            )


async def test_reserved_over_on_hand_is_refused_by_the_check(engine: AsyncEngine) -> None:
    # The CHECK `reserved >= 0 AND reserved <= on_hand`: the ADR 0002 invariant, guarded by
    # the database as well as the domain.
    lab = a_location("WX-L-0001", "Lab")
    part = PartId(uuid7())
    lot = a_lot(part, lab)
    async with inventory(engine) as work:
        await work.locations.add(lab)
        await work.lots.add(lot)
        await work.commit()

    async with inventory(engine) as work:
        with pytest.raises(IntegrityError, match="ck_stock_balances_reserved_within_on_hand"):
            await work.session.execute(
                text(
                    "INSERT INTO stock_balances"
                    " (lot_id, workspace_id, on_hand, reserved, available, version)"
                    " VALUES (:lot, :ws, 5, 9, -4, 0)"
                ),
                {"lot": str(lot.id), "ws": str(BENCH)},
            )


async def test_put_inserts_then_updates_optimistically_on_version(engine: AsyncEngine) -> None:
    # A version-zero put inserts; a bumped put updates the row a version behind. `available`
    # is written from the property, so the derived CHECK holds without the mapping storing it.
    lab = a_location("WX-L-0001", "Lab")
    part = PartId(uuid7())
    lot = a_lot(part, lab)
    async with inventory(engine) as work:
        await work.locations.add(lab)
        await work.lots.add(lot)
        opening = StockBalance.opening(lot.id).apply(a_movement(lot, MovementKind.RECEIVE, 40))
        await work.balances.put(opening)
        await work.commit()

    async with inventory(engine) as work:
        stored = await work.balances.get(lot.id)
        assert stored is not None
        assert (int(stored.on_hand), stored.version) == (40, 1)
        moved = stored.apply(a_movement(lot, MovementKind.ADJUST, -15))
        await work.balances.put(moved)
        await work.commit()

    async with inventory(engine) as work:
        after = await work.balances.get(lot.id)
        assert after is not None
        assert (int(after.on_hand), int(after.available), after.version) == (25, 25, 2)


async def test_a_stale_put_touches_no_row(engine: AsyncEngine) -> None:
    # A put whose version doesn't match the stored one loses the race: no row is updated, so
    # the use case reloads and retries (requirement 5.5).
    lab = a_location("WX-L-0001", "Lab")
    part = PartId(uuid7())
    lot = a_lot(part, lab)
    async with inventory(engine) as work:
        await work.locations.add(lab)
        await work.lots.add(lot)
        first = StockBalance.opening(lot.id).apply(a_movement(lot, MovementKind.RECEIVE, 40))
        await work.balances.put(first)
        # A stale write: it thinks the stored version is 5, but it is 0. It updates nothing.
        stale = StockBalance(lot.id, Quantity(999), Quantity(0), version=6)
        await work.balances.put(stale)
        await work.commit()

    async with inventory(engine) as work:
        after = await work.balances.get(lot.id)
        assert after is not None
        assert (int(after.on_hand), after.version) == (40, 1)


async def test_per_part_totals_come_in_one_grouped_query(engine: AsyncEngine) -> None:
    # Two lots of one part across two locations, one lot of another: the totals sum a part's
    # lots and a part with no stock reads as absent, all in one query (7.1, 7.2).
    lab = a_location("WX-L-0001", "Lab")
    shelf = a_location("WX-L-0002", "Shelf")
    part = PartId(uuid7())
    other = PartId(uuid7())
    unstocked = PartId(uuid7())
    lab_lot = a_lot(part, lab)
    shelf_lot = a_lot(part, shelf)
    other_lot = a_lot(other, lab)
    async with inventory(engine) as work:
        for location in (lab, shelf):
            await work.locations.add(location)
        for lot, quantity in ((lab_lot, 100), (shelf_lot, 40), (other_lot, 7)):
            await work.lots.add(lot)
            await work.balances.put(
                StockBalance.opening(lot.id).apply(a_movement(lot, MovementKind.RECEIVE, quantity))
            )
        await work.commit()

    async with inventory(engine) as work:
        with counting(engine) as statements:
            totals = await work.balances.totals_by_part([part, other, unstocked])
        breakdown = await work.balances.by_part(part)

    assert totals == {part: 140, other: 7}
    assert len(statements) == 1, statements
    # The breakdown carries each location and its on_hand, ordered by code.
    assert [(str(row.location.code), int(row.on_hand)) for row in breakdown] == [
        ("WX-L-0001", 100),
        ("WX-L-0002", 40),
    ]


async def test_replace_all_rewrites_the_projection(engine: AsyncEngine) -> None:
    # `wiredex stock rebuild` clears the workspace's balances and writes the folded ones; a
    # tampered row is gone afterwards (requirement 5.2).
    lab = a_location("WX-L-0001", "Lab")
    part = PartId(uuid7())
    lot = a_lot(part, lab)
    async with inventory(engine) as work:
        await work.locations.add(lab)
        await work.lots.add(lot)
        await work.balances.put(
            StockBalance.opening(lot.id).apply(a_movement(lot, MovementKind.RECEIVE, 999))
        )
        await work.commit()

    async with inventory(engine) as work:
        rebuilt = StockBalance.opening(lot.id).apply(a_movement(lot, MovementKind.RECEIVE, 50))
        await work.balances.replace_all([rebuilt])
        await work.commit()

    async with inventory(engine) as work:
        after = await work.balances.get(lot.id)
        assert after is not None
        assert int(after.on_hand) == 50
