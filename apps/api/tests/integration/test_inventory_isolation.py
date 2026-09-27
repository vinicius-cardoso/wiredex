"""Workspace isolation over the inventory tables, as the role the API logs in with.

The repositories filter `workspace_id` themselves, but that is a promise the code makes. This
is the gate underneath it (ADR 0007): as `wiredex_app`, another workspace's inventory isn't
there to be read, written or moved, filter or no filter — locations, lots, movements and the
short-code counter alike.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid7

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.settings import Environment, Settings
from wiredex.inventory.application.ports import ShortCodeKind
from wiredex.inventory.domain.ledger import StockMovement
from wiredex.inventory.domain.location import Location
from wiredex.inventory.domain.lot import StockLot
from wiredex.inventory.domain.values import (
    LocationId,
    LocationName,
    MovementKind,
    PartId,
    ShortCode,
    StockLotId,
    StockMovementId,
    WorkspaceId,
)
from wiredex.inventory.infrastructure.unit_of_work import SqlInventoryUnitOfWork

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

NOW = datetime(2026, 9, 26, 10, tzinfo=UTC)
MINE = WorkspaceId(uuid7())
THEIRS = WorkspaceId(uuid7())
INVENTORY_TABLES = "stock_movements, stock_balances, stock_lots, short_code_counters, locations"


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
        await connection.execute(text(f"TRUNCATE {INVENTORY_TABLES} CASCADE"))


@pytest.fixture
async def app(app_database_url: str) -> AsyncIterator[AsyncEngine]:
    """The API's role, with the API's engine: row security applies."""
    settings = Settings(environment=Environment.TEST, database_url=SecretStr(app_database_url))
    engine = create_engine(settings)
    yield engine
    await engine.dispose()


def inventory(engine: AsyncEngine, workspace_id: WorkspaceId) -> SqlInventoryUnitOfWork:
    return SqlInventoryUnitOfWork(create_session_factory(engine), workspace_id)


async def seed_my_bench(engine: AsyncEngine) -> tuple[Location, StockLot, StockMovement]:
    """One location, one lot and one movement, all of them mine."""
    lab = Location(
        LocationId(uuid7()), MINE, None, ShortCode("WX-L-0001"), LocationName("Lab"), NOW
    )
    part = PartId(uuid7())
    lot = StockLot(StockLotId(uuid7()), MINE, part, lab.id, NOW)
    movement = StockMovement(
        StockMovementId(uuid7()),
        MINE,
        lot.id,
        MovementKind.RECEIVE,
        100,
        None,
        None,
        None,
        None,
        NOW,
    )
    async with inventory(engine, MINE) as work:
        await work.locations.add(lab)
        await work.lots.add(lot)
        await work.ledger.append(movement)
        await work.short_codes.next(ShortCodeKind.LOCATION)
        await work.commit()
    return lab, lot, movement


async def location_names(engine: AsyncEngine) -> list[str]:
    async with engine.connect() as connection:
        rows = await connection.execute(text("SELECT name FROM locations ORDER BY name"))
        return list(rows.scalars())


async def counter_values(engine: AsyncEngine) -> list[int]:
    async with engine.connect() as connection:
        rows = await connection.execute(
            text("SELECT next_value FROM short_code_counters ORDER BY next_value")
        )
        return list(rows.scalars())


async def test_my_own_bench_is_readable(app: AsyncEngine) -> None:
    lab, lot, movement = await seed_my_bench(app)

    async with inventory(app, MINE) as work:
        assert [location.id for location in await work.locations.all()] == [lab.id]
        found_lot = await work.lots.get(lot.id)
        assert found_lot is not None
        assert [m.id for m in await work.ledger.movements_of(lot.id)] == [movement.id]


async def test_another_workspace_sees_none_of_it(app: AsyncEngine) -> None:
    lab, lot, _ = await seed_my_bench(app)

    async with inventory(app, THEIRS) as work:
        assert await work.locations.all() == []
        assert await work.locations.get(lab.id) is None
        assert await work.lots.get(lot.id) is None
        assert await work.lots.for_part_at(PartId(uuid7()), lab.id) is None
        assert await work.locations.has_lots(lab.id) is False
        assert await work.ledger.movements_of(lot.id) == []
        assert [m async for m in work.ledger.all()] == []


async def test_a_lot_cannot_be_written_into_another_workspace(app: AsyncEngine) -> None:
    lab, _, _ = await seed_my_bench(app)
    planted = StockLot(StockLotId(uuid7()), MINE, PartId(uuid7()), lab.id, NOW)  # my workspace

    async with inventory(app, THEIRS) as work:
        await work.lots.add(planted)
        with pytest.raises(ProgrammingError, match="row-level security"):
            await work.commit()


async def test_a_write_without_a_filter_cannot_touch_another_workspace(
    app: AsyncEngine, admin: AsyncEngine
) -> None:
    await seed_my_bench(app)

    async with inventory(app, THEIRS) as work:
        # No WHERE at all: the policy is what keeps these from reaching my rows.
        await work.session.execute(text("UPDATE locations SET name = 'Stolen'"))
        await work.session.execute(text("DELETE FROM stock_movements"))
        await work.session.execute(text("DELETE FROM locations"))
        await work.commit()

    assert await location_names(admin) == ["Lab"]


async def test_a_read_without_a_filter_sees_one_workspace(app: AsyncEngine) -> None:
    await seed_my_bench(app)

    async with inventory(app, THEIRS) as work:
        theirs = await work.session.scalar(text("SELECT count(*) FROM locations"))
    async with inventory(app, MINE) as work:
        mine = await work.session.scalar(text("SELECT count(*) FROM locations"))

    assert (theirs, mine) == (0, 1)


async def test_another_workspace_cannot_touch_my_counter(
    app: AsyncEngine, admin: AsyncEngine
) -> None:
    # My seed advanced the counter to 2 (next_value after handing out 1). Another workspace
    # minting a number can't reach my row: it inserts its own, mine is left at 2.
    await seed_my_bench(app)

    async with inventory(app, THEIRS) as work:
        their_number = await work.short_codes.next(ShortCodeKind.LOCATION)
        await work.commit()

    # A blind update as the other workspace, no WHERE at all: the policy scopes it to their
    # own row, so mine is untouched even though the statement names no workspace.
    async with inventory(app, THEIRS) as work:
        await work.session.execute(text("UPDATE short_code_counters SET next_value = 999"))
        await work.commit()

    assert their_number == 1
    # The owner sees both rows: mine still at 2 (the seed's mint), theirs blindly set to 999.
    assert await counter_values(admin) == [2, 999]
