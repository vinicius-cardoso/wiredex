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

from support.identity import ManualClock, NewIds
from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.settings import Environment, Settings
from wiredex.inventory.application.builds import LotTake, RevisionStock
from wiredex.inventory.application.ports import ShortCodeKind
from wiredex.inventory.domain.ledger import StockMovement
from wiredex.inventory.domain.location import Location
from wiredex.inventory.domain.lot import StockBalance, StockLot
from wiredex.inventory.domain.unit import Unit, UnitStatus
from wiredex.inventory.domain.values import (
    LocationId,
    LocationName,
    Mac,
    MovementKind,
    PartId,
    RevisionId,
    Serial,
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

NOW = datetime(2026, 9, 26, 10, tzinfo=UTC)
MINE = WorkspaceId(uuid7())
THEIRS = WorkspaceId(uuid7())
INVENTORY_TABLES = (
    "units, stock_movements, stock_balances, stock_lots, short_code_counters, locations"
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


async def seed_my_bench(engine: AsyncEngine) -> tuple[Location, StockLot, StockMovement, Unit]:
    """One location, one lot, one movement and one unit, all of them mine."""
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
    unit = Unit(
        UnitId(uuid7()),
        MINE,
        part,
        lot.id,
        ShortCode("WX-U-0001"),
        Serial("SN-MINE"),
        Mac("aa:bb:cc:dd:ee:ff"),
        UnitStatus.IN_STOCK,
        NOW,
    )
    async with inventory(engine, MINE) as work:
        await work.locations.add(lab)
        await work.lots.add(lot)
        await work.ledger.append(movement)
        await work.units.add(unit)
        await work.short_codes.next(ShortCodeKind.LOCATION)
        await work.commit()
    return lab, lot, movement, unit


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
    lab, lot, movement, unit = await seed_my_bench(app)

    async with inventory(app, MINE) as work:
        assert [location.id for location in await work.locations.all()] == [lab.id]
        found_lot = await work.lots.get(lot.id)
        assert found_lot is not None
        assert [m.id for m in await work.ledger.movements_of(lot.id)] == [movement.id]
        assert await work.units.get(unit.id) is not None
        assert [u.id for u in await work.units.of_ids([unit.id])] == [unit.id]
        assert [u.id for u in await work.units.of_lot(lot.id)] == [unit.id]


async def test_another_workspace_sees_none_of_it(app: AsyncEngine) -> None:
    lab, lot, _, unit = await seed_my_bench(app)

    async with inventory(app, THEIRS) as work:
        assert await work.locations.all() == []
        assert await work.locations.get(lab.id) is None
        assert await work.lots.get(lot.id) is None
        assert await work.lots.for_part_at(PartId(uuid7()), lab.id) is None
        assert await work.locations.has_lots(lab.id) is False
        assert await work.ledger.movements_of(lot.id) == []
        assert [m async for m in work.ledger.all()] == []
        # A unit of mine is invisible by id, by lot, by location and to a search (7.1, 7.2, 7.3),
        # and to the read another module's directory makes by ids (15-flash-log 6.2).
        assert await work.units.get(unit.id) is None
        assert await work.units.of_ids([unit.id]) == []
        assert await work.units.of_lot(lot.id) == []
        assert await work.units.of_part(unit.part_id) == []
        assert await work.units.of_location(lab.id) == []
        assert await work.units.in_stock_at(lot.id) == 0
        assert await work.units.search("WX-U-") == []
        assert await work.units.search("SN-MINE") == []
        assert await work.units.search("aa:bb:cc") == []
        # And its identity isn't taken from their side: they may reuse the serial and MAC.
        assert await work.units.serial_taken(unit.part_id, Serial("SN-MINE")) is False
        assert await work.units.mac_taken(Mac("aa:bb:cc:dd:ee:ff")) is False


async def test_a_unit_cannot_be_written_into_another_workspace(app: AsyncEngine) -> None:
    _, lot, _, _ = await seed_my_bench(app)
    # A unit tagged with my workspace, pushed through their unit of work: the policy's WITH
    # CHECK refuses the insert on commit (requirement 7.1).
    planted = Unit(
        UnitId(uuid7()),
        MINE,
        PartId(uuid7()),
        lot.id,
        ShortCode("WX-U-9999"),
        None,
        None,
        UnitStatus.IN_STOCK,
        NOW,
    )

    async with inventory(app, THEIRS) as work:
        await work.units.add(planted)
        with pytest.raises(ProgrammingError, match="row-level security"):
            await work.commit()


async def test_a_lot_cannot_be_written_into_another_workspace(app: AsyncEngine) -> None:
    lab, _, _, _ = await seed_my_bench(app)
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


# --- The revision's stock, as wiredex_app (requirement 11.2, task 7) -------------------------

# `RevisionStock` runs on `SqlInventoryRepositories` bound to a session another module's unit
# of work opened and set the workspace on (design decision 8). Row-level security is what makes
# that safe: a build transition in one bench can neither read nor reserve another bench's stock,
# and the RESERVE it writes is stamped with — and scoped to — the transition's own workspace.


def a_revision_stock(work: SqlInventoryUnitOfWork, workspace_id: WorkspaceId) -> RevisionStock:
    """`RevisionStock` over repositories on the unit of work's session, as bootstrap binds it."""
    repositories = SqlInventoryRepositories(work.session, workspace_id)
    return RevisionStock(repositories, workspace_id, ManualClock(NOW), NewIds())


async def seed_a_stocked_lot(engine: AsyncEngine) -> tuple[PartId, StockLotId]:
    """A location, a lot and a balance of 5 on hand, all mine, so a reserve has stock to lock."""
    lab = Location(
        LocationId(uuid7()), MINE, None, ShortCode("WX-L-0001"), LocationName("Lab"), NOW
    )
    part = PartId(uuid7())
    lot = StockLot(StockLotId(uuid7()), MINE, part, lab.id, NOW)
    receive = StockMovement(
        StockMovementId(uuid7()), MINE, lot.id, MovementKind.RECEIVE, 5, None, None, None, None, NOW
    )
    async with inventory(engine, MINE) as work:
        await work.locations.add(lab)
        await work.lots.add(lot)
        await work.ledger.append(receive)
        await work.balances.put(StockBalance.opening(lot.id).apply(receive))
        await work.commit()
    return part, lot.id


async def test_another_workspace_reserving_sees_none_of_my_stock(app: AsyncEngine) -> None:
    # A build transition in another bench locks my part's lots through RevisionStock: row-level
    # security hides them, so it finds no stock to reserve (requirement 11.2).
    part, _ = await seed_a_stocked_lot(app)

    async with inventory(app, THEIRS) as work:
        locked = await a_revision_stock(work, THEIRS).available([part], [])

    assert locked.lots == ()
    assert locked.units == ()


async def test_a_reserve_is_written_under_its_own_workspace(app: AsyncEngine) -> None:
    # My own build transition reserves my stock and the RESERVE lands, stamped MINE; the row
    # is scoped to my bench, invisible to another (requirement 11.2).
    part, lot_id = await seed_a_stocked_lot(app)
    revision = RevisionId(uuid7())

    async with inventory(app, MINE) as work:
        stock = a_revision_stock(work, MINE)
        locked = await stock.available([part], [])
        assert [row.lot.id for row in locked.lots] == [lot_id]
        await stock.reserve(locked, revision, [LotTake(lot_id, 2, ())])
        await work.commit()

    # Mine: the reservation is there, one RESERVE of 2, the balance's reserved raised.
    async with inventory(app, MINE) as work:
        held = await a_revision_stock(work, MINE).holdings(revision)
        balance = await work.balances.get(lot_id)
    assert {h.lot_id: h.quantity for h in held.reserved} == {lot_id: 2}
    assert balance is not None
    assert int(balance.reserved) == 2

    # Theirs: the movement and the balance are simply not there to read.
    async with inventory(app, THEIRS) as work:
        assert (await a_revision_stock(work, THEIRS).holdings(revision)).reserved == ()
        assert await work.balances.get(lot_id) is None


async def test_another_workspace_never_reaches_my_trash(app: AsyncEngine) -> None:
    # 16's requirements 8.1 and 8.2: as wiredex_app, their bench lists none of my trash, and
    # can neither restore nor delete for good a unit of mine.
    _, _, _, unit = await seed_my_bench(app)
    async with inventory(app, MINE) as work:
        mine = await work.units.get(unit.id)
        assert mine is not None
        mine.status = UnitStatus.RETIRED
        mine.move_to_trash(NOW)
        await work.commit()

    async with inventory(app, THEIRS) as work:
        assert await work.units.trashed(None, 50) == []
        assert await work.units.in_trash(unit.id) is None
        assert await work.units.empty_trash() == 0
        await work.commit()

    async with inventory(app, MINE) as work:
        assert [found.id for found in await work.units.trashed(None, 50)] == [unit.id]
