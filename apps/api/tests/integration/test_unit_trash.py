"""Units in the trash over Postgres, as `wiredex_app` (16-soft-delete-and-trash, task 4).

What only the database can show: every read of `SqlUnits` leaving a unit in the trash out while
its serial and MAC stay held, a page of the trash in one statement, a restore and a delete for
good of one unit taking turns, and an un-retire queued behind a move to the trash finding no
unit, so no unit in the trash is ever counted in stock again.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID, uuid7

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from support.sql import counting
from wiredex.bootstrap.catalog import catalog_use_cases
from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.inventory import inventory_use_cases
from wiredex.bootstrap.settings import Environment, Settings
from wiredex.catalog.application.categories import NewCategory
from wiredex.catalog.application.parts import NewPart
from wiredex.catalog.domain.part import PartDetails
from wiredex.catalog.domain.values import CategoryName, PartName
from wiredex.catalog.domain.values import WorkspaceId as CatalogWorkspaceId
from wiredex.inventory.application.ports import NewLocation
from wiredex.inventory.application.trash import DeleteUnitForGood, RestoreUnit
from wiredex.inventory.application.units import NewUnit, UnitOfWorkFactory, UnitReceipt
from wiredex.inventory.domain.errors import UnitNotFoundError
from wiredex.inventory.domain.unit import Unit, UnitStatus
from wiredex.inventory.domain.values import LocationName, Mac, PartId, Serial, WorkspaceId
from wiredex.inventory.infrastructure.unit_of_work import SqlInventoryUnitOfWork

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

BENCH = WorkspaceId(uuid7())
TABLES = (
    "units, stock_movements, stock_balances, stock_lots, short_code_counters, locations,"
    " part_definitions, attribute_definitions, categories"
)


@pytest.fixture
async def admin(migrated_database_url: str) -> AsyncIterator[AsyncEngine]:
    """The schema owner, which the policies don't apply to: it sees every workspace."""
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


@pytest.fixture
def sessions(app: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(app)


def inventory(sessions: async_sessionmaker[AsyncSession]) -> SqlInventoryUnitOfWork:
    return SqlInventoryUnitOfWork(sessions, BENCH)


async def boards(sessions: async_sessionmaker[AsyncSession], *labels: NewUnit) -> list[Unit]:
    """ESP32 boards received into a box, one per label, coded from WX-U-0001 in that order."""
    catalog = catalog_use_cases(sessions)
    here = CatalogWorkspaceId(BENCH)
    created = await catalog.create_category(here, NewCategory(CategoryName("Boards")))
    await catalog.set_category_tracking(here, created.category.id, True)
    part = await catalog.define_part(
        here, NewPart(created.category.id, PartDetails(PartName("ESP32-DevKitC")))
    )
    use_cases = inventory_use_cases(sessions)
    box = await use_cases.create_location(BENCH, NewLocation(LocationName("Box")))
    received = await use_cases.receive_units(BENCH, UnitReceipt(PartId(part.id), box.id, labels))
    return list(received.units)


async def trashed(sessions: async_sessionmaker[AsyncSession], unit: Unit) -> None:
    """Retired, then moved to the trash, through the routes' own use cases."""
    use_cases = inventory_use_cases(sessions)
    await use_cases.retire_unit(BENCH, unit.id)
    await use_cases.delete_unit(BENCH, unit.id)


async def test_a_unit_in_the_trash_is_absent_from_every_read(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    gone, kept = await boards(
        sessions, NewUnit(Serial("SN-1"), Mac("aa:bb:cc:dd:ee:ff")), NewUnit()
    )
    await trashed(sessions, gone)

    async with inventory(sessions) as work:
        assert await work.units.get(gone.id) is None
        assert [unit.id for unit in await work.units.of_ids([gone.id, kept.id])] == [kept.id]
        assert [unit.id for unit in await work.units.of_part(gone.part_id)] == [kept.id]
        assert [unit.id for unit in await work.units.of_lot(gone.lot_id)] == [kept.id]
        lot = await work.lots.get(gone.lot_id)
        assert lot is not None
        assert [unit.id for unit in await work.units.of_location(lot.location_id)] == [kept.id]
        assert [unit.id for unit in await work.units.search("WX-U")] == [kept.id]
        assert [unit.id for unit in await work.units.lock([gone.id, kept.id])] == [kept.id]
        # Its serial and MAC stay held (16's decision 5).
        assert await work.units.serial_taken(gone.part_id, Serial("sn-1"))
        assert await work.units.mac_taken(Mac("aa:bb:cc:dd:ee:ff"))


async def test_the_trash_is_read_newest_first_a_page_in_one_statement(
    app: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    first, second, third = await boards(sessions, NewUnit(), NewUnit(), NewUnit())
    for unit in (first, second, third):
        await trashed(sessions, unit)

    async with inventory(sessions) as work:
        with counting(app) as statements:
            page = await work.units.trashed(None, 2)
        assert [unit.id for unit in page] == [third.id, second.id]
        assert len(statements) == 1


async def test_a_restored_unit_comes_back_retired_and_a_deleted_one_keeps_its_ledger(
    admin: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    back, gone = await boards(sessions, NewUnit(), NewUnit())
    await trashed(sessions, back)
    await trashed(sessions, gone)
    factory = inventory_factory(sessions)

    await RestoreUnit(factory)(BENCH, back.id)
    await DeleteUnitForGood(factory)(BENCH, gone.id)

    async with admin.connect() as connection:
        units = (await connection.execute(text("SELECT id, status, trashed_at FROM units"))).all()
        movements = await connection.scalar(text("SELECT count(*) FROM stock_movements"))
    assert [tuple(row) for row in units] == [(back.id, "retired", None)]
    # The receipt of two, then a retire of each: deleting a unit for good keeps its movements.
    assert movements == 3


def inventory_factory(sessions: async_sessionmaker[AsyncSession]) -> UnitOfWorkFactory:
    return lambda workspace_id: SqlInventoryUnitOfWork(sessions, workspace_id)


@asynccontextmanager
async def unit_held(admin: AsyncEngine, unit_id: UUID) -> AsyncIterator[None]:
    """The unit's row locked by an outside transaction until the block ends, so the requests
    line up behind it in the order they asked for it."""
    async with admin.begin() as holder:
        await holder.execute(
            text("SELECT id FROM units WHERE id = :id FOR UPDATE"), {"id": unit_id}
        )
        yield


async def until_waiting(admin: AsyncEngine, count: int) -> None:
    for _ in range(200):
        async with admin.connect() as watcher:
            waiting = await watcher.scalar(
                text("SELECT count(*) FROM pg_stat_activity WHERE wait_event_type = 'Lock'")
            )
        if (waiting or 0) >= count:
            return
        await asyncio.sleep(0.05)
    pytest.fail(f"expected {count} transactions waiting for the unit's lock")


async def test_an_unretire_queued_behind_a_move_to_the_trash_finds_no_unit(
    admin: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    # Requirement 1.5: the un-retire's lock is taken once the move commits, and Postgres checks
    # its `trashed_at IS NULL` again against that row. Without it the un-retire would put a
    # unit in the trash back in stock, counted and nowhere to be seen.
    [board] = await boards(sessions, NewUnit())
    use_cases = inventory_use_cases(sessions)
    await use_cases.retire_unit(BENCH, board.id)

    async with unit_held(admin, board.id):
        move = asyncio.create_task(use_cases.delete_unit(BENCH, board.id))
        await until_waiting(admin, 1)
        unretire = asyncio.create_task(use_cases.unretire_unit(BENCH, board.id))
        await until_waiting(admin, 2)
    await move

    with pytest.raises(UnitNotFoundError):
        await unretire
    async with admin.connect() as connection:
        row = (await connection.execute(text("SELECT status, trashed_at FROM units"))).one()
    assert row.status == UnitStatus.RETIRED
    assert row.trashed_at is not None


async def test_a_restore_and_a_delete_for_good_of_one_unit_take_turns(
    admin: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    # Requirement 5.4: one wins, the other finds nothing, and the unit is back or gone.
    [board] = await boards(sessions, NewUnit())
    await trashed(sessions, board)
    factory = inventory_factory(sessions)

    async with unit_held(admin, board.id):
        racing = [
            asyncio.create_task(RestoreUnit(factory)(BENCH, board.id)),
            asyncio.create_task(DeleteUnitForGood(factory)(BENCH, board.id)),
        ]
        await until_waiting(admin, 2)
    outcomes = await asyncio.gather(*racing, return_exceptions=True)

    assert outcomes.count(None) == 1
    assert len([o for o in outcomes if isinstance(o, UnitNotFoundError)]) == 1
    async with admin.connect() as connection:
        rows = [
            tuple(row) for row in await connection.execute(text("SELECT trashed_at FROM units"))
        ]
    assert rows in ([(None,)], [])
