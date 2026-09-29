"""The units repository against a real PostgreSQL: the partial indexes and the search.

What can only be checked here is what the database enforces: the per-part lower-cased serial
index, the per-workspace MAC index, the three trigram indexes answering a case-insensitive
substring search over code, serial and MAC, and `in_stock_at` counting only `in_stock` units.
The `SqlUnits` reads (`of_part`, `of_lot`, `of_location`) are the queries the joins and the
indexes support, so they are exercised here too.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid7

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from support.sql import counting
from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.settings import Environment, Settings
from wiredex.inventory.domain.location import Location
from wiredex.inventory.domain.lot import StockLot
from wiredex.inventory.domain.unit import Unit, UnitStatus
from wiredex.inventory.domain.values import (
    LocationId,
    LocationName,
    Mac,
    PartId,
    RevisionId,
    Serial,
    ShortCode,
    StockLotId,
    UnitId,
    WorkspaceId,
)
from wiredex.inventory.infrastructure.unit_of_work import SqlInventoryUnitOfWork

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

NOW = datetime(2026, 9, 27, 10, tzinfo=UTC)
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


def a_unit(
    lot: StockLot,
    code: str,
    *,
    serial: Serial | None = None,
    mac: Mac | None = None,
    status: UnitStatus = UnitStatus.IN_STOCK,
) -> Unit:
    # A unit's part is its lot's part, so the lot carries it — no separate argument to keep in
    # step with the lot it points at.
    return Unit(
        UnitId(uuid7()),
        BENCH,
        lot.part_id,
        lot.id,
        ShortCode(code),
        serial,
        mac,
        status,
        NOW,
    )


def held_unit(lot: StockLot, code: str, status: UnitStatus, revision_id: RevisionId) -> Unit:
    """A reserved or in-use unit pointing at its revision, which the table's CHECK requires."""
    unit = a_unit(lot, code, status=status)
    unit.revision_id = revision_id
    return unit


async def test_the_unit_of_work_binds_the_units_repository(engine: AsyncEngine) -> None:
    # The port's `units` is bound and answers inside the `async with`, alongside the others.
    async with inventory(engine) as work:
        assert await work.units.get(UnitId(uuid7())) is None
        assert await work.units.of_part(PartId(uuid7())) == []
        assert await work.units.in_stock_at(StockLotId(uuid7())) == 0
        assert await work.units.search("nothing") == []


async def test_two_units_of_one_part_cannot_share_a_serial(engine: AsyncEngine) -> None:
    # The per-part partial index `(workspace_id, part_id, lower(serial))`: a serial is unique
    # within a part, folding case, so `SN-1` and `sn-1` collide (requirement 5.1).
    lab = a_location("WX-L-0001", "Lab")
    part = PartId(uuid7())
    lot = a_lot(part, lab)
    async with inventory(engine) as work:
        await work.locations.add(lab)
        await work.lots.add(lot)
        await work.units.add(a_unit(lot, "WX-U-0001", serial=Serial("SN-1")))
        await work.commit()

    async with inventory(engine) as work:
        await work.units.add(a_unit(lot, "WX-U-0002", serial=Serial("sn-1")))
        with pytest.raises(IntegrityError, match="uq_units_workspace_id_part_id_serial"):
            await work.commit()


async def test_two_parts_may_reuse_one_serial(engine: AsyncEngine) -> None:
    # The serial index is per part: two different parts each holding "SN-1" is allowed, since
    # a serial only means something within a part (requirement 5.1).
    lab = a_location("WX-L-0001", "Lab")
    one = PartId(uuid7())
    another = PartId(uuid7())
    one_lot = a_lot(one, lab)
    another_lot = a_lot(another, lab)
    async with inventory(engine) as work:
        await work.locations.add(lab)
        await work.lots.add(one_lot)
        await work.lots.add(another_lot)
        await work.units.add(a_unit(one_lot, "WX-U-0001", serial=Serial("SN-1")))
        await work.units.add(a_unit(another_lot, "WX-U-0002", serial=Serial("SN-1")))
        await work.commit()

    async with inventory(engine) as work:
        assert await work.units.serial_taken(one, Serial("sn-1")) is True
        assert await work.units.serial_taken(another, Serial("SN-1")) is True
        assert await work.units.serial_taken(PartId(uuid7()), Serial("SN-1")) is False


async def test_any_number_of_units_may_have_no_serial(engine: AsyncEngine) -> None:
    # The index is partial (`WHERE serial IS NOT NULL`): two units of one part with no serial
    # don't collide (requirement 5.5).
    lab = a_location("WX-L-0001", "Lab")
    part = PartId(uuid7())
    lot = a_lot(part, lab)
    async with inventory(engine) as work:
        await work.locations.add(lab)
        await work.lots.add(lot)
        await work.units.add(a_unit(lot, "WX-U-0001"))
        await work.units.add(a_unit(lot, "WX-U-0002"))
        await work.commit()

    async with inventory(engine) as work:
        assert len(await work.units.of_part(part)) == 2


async def test_two_units_in_one_workspace_cannot_share_a_mac(engine: AsyncEngine) -> None:
    # The per-workspace partial index `(workspace_id, mac)`: a MAC is unique across the whole
    # workspace, whatever the parts, and its spellings are one canonical value (requirement 5.2).
    lab = a_location("WX-L-0001", "Lab")
    one = PartId(uuid7())
    another = PartId(uuid7())
    one_lot = a_lot(one, lab)
    another_lot = a_lot(another, lab)
    async with inventory(engine) as work:
        await work.locations.add(lab)
        await work.lots.add(one_lot)
        await work.lots.add(another_lot)
        await work.units.add(a_unit(one_lot, "WX-U-0001", mac=Mac("aa:bb:cc:dd:ee:ff")))
        await work.commit()

    async with inventory(engine) as work:
        # A different part, a different spelling of the same address: still a collision.
        clash = a_unit(another_lot, "WX-U-0002", mac=Mac("AA-BB-CC-DD-EE-FF"))
        await work.units.add(clash)
        with pytest.raises(IntegrityError, match="uq_units_workspace_id_mac"):
            await work.commit()


async def test_mac_taken_sees_the_canonical_address(engine: AsyncEngine) -> None:
    lab = a_location("WX-L-0001", "Lab")
    part = PartId(uuid7())
    lot = a_lot(part, lab)
    async with inventory(engine) as work:
        await work.locations.add(lab)
        await work.lots.add(lot)
        await work.units.add(a_unit(lot, "WX-U-0001", mac=Mac("aabb.ccdd.eeff")))
        await work.commit()

    async with inventory(engine) as work:
        # Any spelling normalizes to the stored canonical value, so it is seen as taken.
        assert await work.units.mac_taken(Mac("aabbccddeeff")) is True
        assert await work.units.mac_taken(Mac("11:22:33:44:55:66")) is False


async def test_search_matches_code_serial_and_mac(engine: AsyncEngine) -> None:
    # The three trigram indexes: a term finds a unit by code, serial or MAC, ignoring case,
    # and never a unit that matches none (requirements 6.3, 2.5).
    lab = a_location("WX-L-0001", "Lab")
    part = PartId(uuid7())
    lot = a_lot(part, lab)
    by_code = a_unit(lot, "WX-U-0042")
    by_serial = a_unit(lot, "WX-U-0043", serial=Serial("ESP-Z9"))
    by_mac = a_unit(lot, "WX-U-0044", mac=Mac("aa:bb:cc:dd:ee:ff"))
    async with inventory(engine) as work:
        await work.locations.add(lab)
        await work.lots.add(lot)
        for unit in (by_code, by_serial, by_mac):
            await work.units.add(unit)
        await work.commit()

    async with inventory(engine) as work:
        assert [u.id for u in await work.units.search("0042")] == [by_code.id]
        assert [u.id for u in await work.units.search("esp-z9")] == [by_serial.id]
        assert [u.id for u in await work.units.search("cc:dd")] == [by_mac.id]
        # The shared WX-U- prefix returns all three, in code order.
        assert [str(u.code) for u in await work.units.search("wx-u-")] == [
            "WX-U-0042",
            "WX-U-0043",
            "WX-U-0044",
        ]
        assert await work.units.search("9999") == []


async def test_in_stock_at_counts_only_in_stock_units(engine: AsyncEngine) -> None:
    # `in_stock_at` is the count the invariant compares to a lot's on_hand: a retired unit,
    # and a unit in another lot, are not counted (requirement 9.1).
    lab = a_location("WX-L-0001", "Lab")
    shelf = a_location("WX-L-0002", "Shelf")
    part = PartId(uuid7())
    lab_lot = a_lot(part, lab)
    shelf_lot = a_lot(part, shelf)
    async with inventory(engine) as work:
        await work.locations.add(lab)
        await work.locations.add(shelf)
        await work.lots.add(lab_lot)
        await work.lots.add(shelf_lot)
        await work.units.add(a_unit(lab_lot, "WX-U-0001"))
        await work.units.add(a_unit(lab_lot, "WX-U-0002"))
        await work.units.add(a_unit(lab_lot, "WX-U-0003", status=UnitStatus.RETIRED))
        await work.units.add(a_unit(shelf_lot, "WX-U-0004"))
        await work.commit()

    async with inventory(engine) as work:
        assert await work.units.in_stock_at(lab_lot.id) == 2
        assert await work.units.in_stock_at(shelf_lot.id) == 1


async def test_of_lot_and_of_location_read_the_right_units(engine: AsyncEngine) -> None:
    # `of_lot` is a lot's units; `of_location` joins units to lots and keeps a whole location's,
    # across its lots and parts, never another location's (requirement 6.2).
    lab = a_location("WX-L-0001", "Lab")
    shelf = a_location("WX-L-0002", "Shelf")
    one = PartId(uuid7())
    another = PartId(uuid7())
    lab_lot_one = a_lot(one, lab)
    lab_lot_another = a_lot(another, lab)
    shelf_lot = a_lot(one, shelf)
    here_a = a_unit(lab_lot_one, "WX-U-0001")
    here_b = a_unit(lab_lot_another, "WX-U-0002")
    there = a_unit(shelf_lot, "WX-U-0003")
    async with inventory(engine) as work:
        await work.locations.add(lab)
        await work.locations.add(shelf)
        for lot in (lab_lot_one, lab_lot_another, shelf_lot):
            await work.lots.add(lot)
        for unit in (here_a, here_b, there):
            await work.units.add(unit)
        await work.commit()

    async with inventory(engine) as work:
        assert [u.id for u in await work.units.of_lot(lab_lot_one.id)] == [here_a.id]
        assert {u.id for u in await work.units.of_location(lab.id)} == {here_a.id, here_b.id}
        assert [u.id for u in await work.units.of_location(shelf.id)] == [there.id]


async def test_of_revision_reads_a_revisions_units_with_their_location(engine: AsyncEngine) -> None:
    # A revision's held units, joined to their lots and locations in one query: a reserved unit
    # answers its location code, an in-use one answers none — it sits on a board (3.11, 5).
    lab = a_location("WX-L-0001", "Lab")
    part = PartId(uuid7())
    lot = a_lot(part, lab)
    revision = RevisionId(uuid7())
    reserved = held_unit(lot, "WX-U-0001", UnitStatus.RESERVED, revision)
    built = held_unit(lot, "WX-U-0002", UnitStatus.IN_USE, revision)
    other = a_unit(lot, "WX-U-0003")  # in stock, another revision's — not this one's
    async with inventory(engine) as work:
        await work.locations.add(lab)
        await work.lots.add(lot)
        for unit in (reserved, built, other):
            await work.units.add(unit)
        await work.commit()

    async with inventory(engine) as work:
        with counting(engine) as statements:
            rows = await work.units.of_revision(revision)

    assert [(str(row.unit.code), row.location_code) for row in rows] == [
        ("WX-U-0001", "WX-L-0001"),
        ("WX-U-0002", None),
    ]
    assert len(statements) == 1, statements


async def test_lock_takes_units_by_id_and_refreshes_the_session(engine: AsyncEngine) -> None:
    # FOR UPDATE by id, with populate_existing so a row already read is refreshed with what the
    # lock saw; an id the workspace doesn't hold is simply absent (decision 10).
    lab = a_location("WX-L-0001", "Lab")
    part = PartId(uuid7())
    lot = a_lot(part, lab)
    one = a_unit(lot, "WX-U-0001")
    two = a_unit(lot, "WX-U-0002")
    async with inventory(engine) as work:
        await work.locations.add(lab)
        await work.lots.add(lot)
        await work.units.add(one)
        await work.units.add(two)
        await work.commit()

    async with inventory(engine) as work:
        locked = await work.units.lock(sorted([two.id, one.id, UnitId(uuid7())]))

    assert {unit.id for unit in locked} == {one.id, two.id}


async def test_in_stock_of_parts_takes_only_in_stock_units(engine: AsyncEngine) -> None:
    lab = a_location("WX-L-0001", "Lab")
    part = PartId(uuid7())
    other = PartId(uuid7())
    lot = a_lot(part, lab)
    other_lot = a_lot(other, lab)
    revision = RevisionId(uuid7())
    in_stock = a_unit(lot, "WX-U-0001")
    reserved = held_unit(lot, "WX-U-0002", UnitStatus.RESERVED, revision)
    other_part = a_unit(other_lot, "WX-U-0003")
    async with inventory(engine) as work:
        await work.locations.add(lab)
        await work.lots.add(lot)
        await work.lots.add(other_lot)
        for unit in (in_stock, reserved, other_part):
            await work.units.add(unit)
        await work.commit()

    async with inventory(engine) as work:
        found = await work.units.in_stock_of_parts([part])

    # Only the in-stock unit of the asked part: the reserved one and the other part are out.
    assert [unit.id for unit in found] == [in_stock.id]


async def test_of_lot_reserved_counts_only_reserved_units(engine: AsyncEngine) -> None:
    lab = a_location("WX-L-0001", "Lab")
    part = PartId(uuid7())
    lot = a_lot(part, lab)
    revision = RevisionId(uuid7())
    async with inventory(engine) as work:
        await work.locations.add(lab)
        await work.lots.add(lot)
        await work.units.add(a_unit(lot, "WX-U-0001"))
        await work.units.add(held_unit(lot, "WX-U-0002", UnitStatus.RESERVED, revision))
        await work.units.add(held_unit(lot, "WX-U-0003", UnitStatus.RESERVED, revision))
        await work.commit()

    async with inventory(engine) as work:
        assert await work.units.of_lot_reserved(lot.id) == 2


async def test_the_new_reads_answer_empty_for_empty_input(engine: AsyncEngine) -> None:
    # The guards RevisionStock leans on: a reserve with no units, or a cancel of a revision
    # holding no units, asks for nothing and gets nothing without a query.
    async with inventory(engine) as work:
        assert await work.units.lock([]) == []
        assert await work.units.in_stock_of_parts([]) == []
