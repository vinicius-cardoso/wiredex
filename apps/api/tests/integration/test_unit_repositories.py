"""The units repository against a real PostgreSQL: the partial indexes and the search.

What can only be checked here is what the database enforces: the per-part lower-cased serial
index, the per-workspace MAC index, the three trigram indexes answering a case-insensitive
substring search over code, serial and MAC, and `in_stock_at` counting only `in_stock` units.
The `SqlUnits` reads (`of_part`, `of_lot`, `of_location`) are the queries the joins and the
indexes support, so they are exercised here too.
"""

import re
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
from wiredex.inventory.application.ports import UnitQuery
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
from wiredex.shared_kernel.domain.paging import MAX_PAGE_SIZE, PageRequest

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

# The first page at its largest, which holds every unit these tests make.
EVERY = PageRequest(1, MAX_PAGE_SIZE)

NOW = datetime(2026, 9, 27, 10, tzinfo=UTC)
BENCH = WorkspaceId(uuid7())
INVENTORY_TABLES = (
    "units, stock_movements, stock_balances, stock_lots, short_code_counters, locations"
)
# Postgres's four row-locking clauses, which a read that promises to lock nothing never sends.
ROW_LOCK = re.compile(r"\bFOR (UPDATE|NO KEY UPDATE|SHARE|KEY SHARE)\b")


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


def received_at(unit: Unit, when: datetime) -> Unit:
    """The unit as received at another time, for the order the boards list reads in."""
    unit.created_at = when
    return unit


async def search(work: SqlInventoryUnitOfWork, term: str) -> list[Unit]:
    """The boards list's search for a term, nothing else narrowing it."""
    return await work.units.search(UnitQuery(term), EVERY)


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
        assert await work.units.search(UnitQuery("nothing"), EVERY) == []


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
        assert [u.id for u in await search(work, "0042")] == [by_code.id]
        assert [u.id for u in await search(work, "esp-z9")] == [by_serial.id]
        assert [u.id for u in await search(work, "cc:dd")] == [by_mac.id]
        # The shared WX-U- prefix returns all three, newest first: received at one time, the
        # id, which UUIDv7 orders by when it was made, breaks the tie.
        assert [str(u.code) for u in await search(work, "wx-u-")] == [
            "WX-U-0044",
            "WX-U-0043",
            "WX-U-0042",
        ]
        assert await search(work, "9999") == []
        # A wildcard is a character: nothing here holds a percent sign.
        assert await search(work, "%") == []


async def test_the_boards_list_is_every_unit_newest_first_in_one_statement(
    engine: AsyncEngine,
) -> None:
    # With nothing typed, every live unit of the bench, the last received first, at most the
    # limit, whatever its status; the status and the part narrow it as equalities.
    lab = a_location("WX-L-0001", "Lab")
    board = PartId(uuid7())
    sensor = PartId(uuid7())
    boards = a_lot(board, lab)
    sensors = a_lot(sensor, lab)
    made = [
        received_at(a_unit(boards, f"WX-U-{number:04}"), NOW + timedelta(minutes=number))
        for number in range(1, 6)
    ]
    retired = a_unit(boards, "WX-U-0006", status=UnitStatus.RETIRED)
    other = received_at(a_unit(sensors, "WX-U-0007"), NOW - timedelta(days=1))
    async with inventory(engine) as work:
        await work.locations.add(lab)
        await work.lots.add(boards)
        await work.lots.add(sensors)
        for unit in (*made, retired, other):
            await work.units.add(unit)
        await work.commit()

    async with inventory(engine) as work:
        with counting(engine) as statements:
            everything = await work.units.search(UnitQuery(), EVERY)
        newest_three = await work.units.search(UnitQuery(), PageRequest(1, 3))
        by_status = await work.units.search(UnitQuery(status=UnitStatus.RETIRED), EVERY)
        by_part = await work.units.search(UnitQuery(part_id=sensor), EVERY)
        narrowed = await work.units.search(UnitQuery("wx-u-000", UnitStatus.IN_STOCK, board), EVERY)

    assert [str(u.code) for u in everything] == [
        "WX-U-0005",
        "WX-U-0004",
        "WX-U-0003",
        "WX-U-0002",
        "WX-U-0001",
        "WX-U-0006",
        "WX-U-0007",
    ]
    assert len(statements) == 1, statements
    assert ROW_LOCK.search(statements[0]) is None, statements
    assert [str(u.code) for u in newest_three] == ["WX-U-0005", "WX-U-0004", "WX-U-0003"]
    assert [u.id for u in by_status] == [retired.id]
    assert [u.id for u in by_part] == [other.id]
    assert [str(u.code) for u in narrowed] == [str(u.code) for u in reversed(made)]


async def test_walking_the_boards_pages_sees_each_unit_once_in_order(engine: AsyncEngine) -> None:
    # Seven units of one receipt share `created_at`, three of a later one share theirs: the id
    # alone orders each receipt, so every unit falls on exactly one page, and the total never
    # moves. Narrowed by status, the count and the rows narrow together.
    lab = a_location("WX-L-0001", "Lab")
    lot = a_lot(PartId(uuid7()), lab)
    first = [
        a_unit(lot, f"WX-U-{number:04}", status=_retired_every_third(number))
        for number in range(1, 8)
    ]
    second = [
        received_at(
            a_unit(lot, f"WX-U-{number:04}", status=_retired_every_third(number)),
            NOW + timedelta(minutes=1),
        )
        for number in range(8, 11)
    ]
    trashed = a_unit(lot, "WX-U-0011", status=UnitStatus.RETIRED)
    trashed.move_to_trash(NOW)
    async with inventory(engine) as work:
        await work.locations.add(lab)
        await work.lots.add(lot)
        for unit in (*first, *second, trashed):
            await work.units.add(unit)
        await work.commit()

    expected = sorted((*first, *second), key=lambda unit: (unit.created_at, unit.id), reverse=True)
    retired = UnitQuery(status=UnitStatus.RETIRED)
    async with inventory(engine) as work:
        with counting(engine) as statements:
            walked, totals = await _walk(work, UnitQuery(), size=3)
        retired_walked, retired_totals = await _walk(work, retired, size=2)

    assert [len(page) for page in walked] == [3, 3, 3, 1]
    assert [unit.id for page in walked for unit in page] == [unit.id for unit in expected]
    assert totals == [10, 10, 10, 10]
    # A count and a page per page, whatever the size.
    assert len(statements) == 8, statements
    assert all(ROW_LOCK.search(statement) is None for statement in statements), statements
    retired_ids = [unit.id for unit in expected if unit.status is UnitStatus.RETIRED]
    assert [len(page) for page in retired_walked] == [2, 1]
    assert [unit.id for page in retired_walked for unit in page] == retired_ids
    assert retired_totals == [3, 3]


def _retired_every_third(number: int) -> UnitStatus:
    """Units 3, 6 and 9 retired: two in the first receipt, one in the second."""
    return UnitStatus.RETIRED if number % 3 == 0 else UnitStatus.IN_STOCK


async def _walk(
    work: SqlInventoryUnitOfWork, query: UnitQuery, size: int
) -> tuple[list[list[Unit]], list[int]]:
    """Every page of the query in turn, each with the total counted beside it."""
    pages: list[list[Unit]] = []
    totals: list[int] = []
    number = 1
    while True:
        total = await work.units.count(query)
        pages.append(await work.units.search(query, PageRequest(number, size)))
        totals.append(total)
        if number * size >= total:
            return pages, totals
        number += 1


async def test_part_counts_counts_each_parts_live_units_in_one_statement(
    engine: AsyncEngine,
) -> None:
    # The boards list's part filter: every part with a live unit, a retired one counting, and
    # a unit in the trash counting for nothing, so a part with only that one is absent.
    lab = a_location("WX-L-0001", "Lab")
    board = PartId(uuid7())
    sensor = PartId(uuid7())
    gone = PartId(uuid7())
    boards, sensors, gone_lot = a_lot(board, lab), a_lot(sensor, lab), a_lot(gone, lab)
    trashed = a_unit(gone_lot, "WX-U-0005", status=UnitStatus.RETIRED)
    trashed.move_to_trash(NOW)
    also_trashed = a_unit(boards, "WX-U-0006", status=UnitStatus.RETIRED)
    also_trashed.move_to_trash(NOW)
    async with inventory(engine) as work:
        await work.locations.add(lab)
        for lot in (boards, sensors, gone_lot):
            await work.lots.add(lot)
        for unit in (
            a_unit(boards, "WX-U-0001"),
            a_unit(boards, "WX-U-0002", status=UnitStatus.RETIRED),
            a_unit(boards, "WX-U-0003"),
            a_unit(sensors, "WX-U-0004"),
            trashed,
            also_trashed,
        ):
            await work.units.add(unit)
        await work.commit()

    async with inventory(engine) as work:
        with counting(engine) as statements:
            counts = await work.units.part_counts()
    async with inventory(engine, WorkspaceId(uuid7())) as elsewhere:
        unseen = await elsewhere.units.part_counts()

    assert counts == {board: 3, sensor: 1}
    assert len(statements) == 1, statements
    assert ROW_LOCK.search(statements[0]) is None, statements
    assert unseen == {}


async def test_locations_of_reads_every_lots_location_in_one_statement(
    engine: AsyncEngine,
) -> None:
    lab = a_location("WX-L-0001", "Lab")
    shelf = a_location("WX-L-0002", "Shelf")
    in_lab = a_lot(PartId(uuid7()), lab)
    on_shelf = a_lot(PartId(uuid7()), shelf)
    async with inventory(engine) as work:
        await work.locations.add(lab)
        await work.locations.add(shelf)
        await work.lots.add(in_lab)
        await work.lots.add(on_shelf)
        await work.commit()

    async with inventory(engine) as work:
        with counting(engine) as statements:
            found = await work.lots.locations_of([in_lab.id, on_shelf.id, StockLotId(uuid7())])
        with counting(engine) as nothing:
            assert await work.lots.locations_of([]) == {}

    assert {lot_id: str(place.code) for lot_id, place in found.items()} == {
        in_lab.id: "WX-L-0001",
        on_shelf.id: "WX-L-0002",
    }
    assert len(statements) == 1, statements
    assert nothing == []


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


async def test_of_ids_reads_forty_units_in_one_unlocked_statement_by_code(
    engine: AsyncEngine,
) -> None:
    # 15-flash-log decision 8: what firmware's unit directory reads, any number of units in one
    # plain SELECT, by code, whatever their status. An id the workspace doesn't hold is absent,
    # and from another workspace's side every one is, by the repository's own filter: this
    # engine is the schema owner, whom row-level security doesn't narrow.
    lab = a_location("WX-L-0001", "Lab")
    lot = a_lot(PartId(uuid7()), lab)
    # Made from the last code down, so neither the ids nor the insertion follow the code order.
    made = [a_unit(lot, f"WX-U-{number:04}") for number in range(40, 1, -1)]
    made.append(a_unit(lot, "WX-U-0001", status=UnitStatus.RETIRED))
    async with inventory(engine) as work:
        await work.locations.add(lab)
        await work.lots.add(lot)
        for unit in made:
            await work.units.add(unit)
        await work.commit()

    wanted = [unit.id for unit in made] + [UnitId(uuid7())]
    async with inventory(engine) as work:
        with counting(engine) as statements:
            found = await work.units.of_ids(wanted)
        with counting(engine) as nothing:
            assert await work.units.of_ids([]) == []
    async with inventory(engine, WorkspaceId(uuid7())) as elsewhere:
        unseen = await elsewhere.units.of_ids(wanted)

    assert [str(unit.code) for unit in found] == [f"WX-U-{number:04}" for number in range(1, 41)]
    assert found[0].status is UnitStatus.RETIRED
    assert len(statements) == 1, statements
    assert ROW_LOCK.search(statements[0]) is None, statements
    assert nothing == []
    assert unseen == []


async def test_status_counts_groups_the_listed_parts_live_units_by_status(
    engine: AsyncEngine,
) -> None:
    # What tells a part's units from its loose stock before it changes how it is counted: one
    # grouped read, the trash and the parts not asked about left out.
    lab = a_location("WX-L-0001", "Lab")
    board, sensor, other = PartId(uuid7()), PartId(uuid7()), PartId(uuid7())
    boards, sensors, others = a_lot(board, lab), a_lot(sensor, lab), a_lot(other, lab)
    trashed = a_unit(boards, "WX-U-0005")
    trashed.move_to_trash(NOW)
    async with inventory(engine) as work:
        await work.locations.add(lab)
        for lot in (boards, sensors, others):
            await work.lots.add(lot)
        for unit in (
            a_unit(boards, "WX-U-0001"),
            a_unit(boards, "WX-U-0002"),
            a_unit(boards, "WX-U-0003", status=UnitStatus.RETIRED),
            a_unit(sensors, "WX-U-0004"),
            trashed,
            a_unit(others, "WX-U-0006"),
        ):
            await work.units.add(unit)
        await work.commit()

    async with inventory(engine) as work:
        with counting(engine) as statements:
            counts = await work.units.status_counts([board, sensor, PartId(uuid7())])
    async with inventory(engine, WorkspaceId(uuid7())) as elsewhere:
        unseen = await elsewhere.units.status_counts([board])

    assert counts == {
        board: {UnitStatus.IN_STOCK: 2, UnitStatus.RETIRED: 1},
        sensor: {UnitStatus.IN_STOCK: 1},
    }
    assert len(statements) == 1, statements
    assert unseen == {}
