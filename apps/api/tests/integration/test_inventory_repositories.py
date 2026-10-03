"""The inventory repositories against a real PostgreSQL: the tree, the indexes, the checks.

What can only be checked here is what the database does: one recursive query for a whole
ancestor chain, the trigram index answering a code search, the balance CHECKs refusing a bad
row, the optimistic-lock retry on `version`, and per-part totals in one grouped query.
"""

from collections.abc import AsyncIterator
from dataclasses import replace
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
from wiredex.inventory.domain.errors import ConcurrentStockError
from wiredex.inventory.domain.ledger import StockMovement
from wiredex.inventory.domain.location import Location
from wiredex.inventory.domain.lot import StockBalance, StockLot
from wiredex.inventory.domain.values import (
    LocationId,
    LocationName,
    MovementKind,
    Note,
    PartId,
    Quantity,
    RevisionId,
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


async def test_lot_counts_counts_every_location_in_one_read(engine: AsyncEngine) -> None:
    lab = a_location("WX-L-0001", "Lab")
    drawer = a_location("WX-L-0002", "Drawer")
    empty = a_location("WX-L-0003", "Empty")
    async with inventory(engine) as work:
        for location in (lab, drawer, empty):
            await work.locations.add(location)
        for location in (lab, lab, drawer):
            await work.lots.add(a_lot(PartId(uuid7()), location))
        await work.commit()

    async with inventory(engine) as work:
        counts = await work.locations.lot_counts()

    # A location holding nothing is left out, and the list reads it as none.
    assert counts == {lab.id: 2, drawer.id: 1}


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


async def test_a_movements_note_is_stored_and_read_back(engine: AsyncEngine) -> None:
    # A receipt with a note answered 500: the column took a string, the entity holds a `Note`.
    lab = a_location("WX-L-0001", "Lab")
    lot = a_lot(PartId(uuid7()), lab)
    noted = replace(a_movement(lot, MovementKind.RECEIVE, 5), note=Note("SMA variant, marked 433M"))
    async with inventory(engine) as work:
        await work.locations.add(lab)
        await work.lots.add(lot)
        await work.ledger.append(noted)
        later = NOW + timedelta(minutes=1)
        await work.ledger.append(a_movement(lot, MovementKind.ADJUST, -1, later))
        await work.commit()

    async with inventory(engine) as work:
        movements = await work.ledger.movements_of(lot.id)

    assert [movement.note for movement in movements] == [Note("SMA variant, marked 433M"), None]


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


async def test_a_stale_put_is_refused_and_changes_nothing(engine: AsyncEngine) -> None:
    # A put whose version doesn't follow the stored one raises, so its transaction, movement
    # included, rolls back: a silent miss would leave the ledger and the balance disagreeing
    # (requirement 5.5).
    lab = a_location("WX-L-0001", "Lab")
    part = PartId(uuid7())
    lot = a_lot(part, lab)
    async with inventory(engine) as work:
        await work.locations.add(lab)
        await work.lots.add(lot)
        await work.balances.put(
            StockBalance.opening(lot.id).apply(a_movement(lot, MovementKind.RECEIVE, 40))
        )
        await work.commit()

    # A stale write: it thinks the stored version is 5, but it is 1.
    stale = StockBalance(lot.id, Quantity(999), Quantity(0), version=6)
    with pytest.raises(ConcurrentStockError):
        await put_in_its_own_transaction(engine, stale)

    async with inventory(engine) as work:
        after = await work.balances.get(lot.id)
        assert after is not None
        assert (int(after.on_hand), after.version) == (40, 1)


async def put_in_its_own_transaction(engine: AsyncEngine, balance: StockBalance) -> None:
    async with inventory(engine) as work:
        await work.balances.put(balance)
        await work.commit()


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


async def test_what_a_location_holds_comes_in_one_statement(engine: AsyncEngine) -> None:
    # The location's page: each lot sitting in it with its on hand and reserved, a lot with no
    # balance yet holding nothing, never another location's lot.
    lab = a_location("WX-L-0001", "Lab")
    shelf = a_location("WX-L-0002", "Shelf")
    stocked = a_lot(PartId(uuid7()), lab)
    fresh = a_lot(PartId(uuid7()), lab)
    elsewhere = a_lot(PartId(uuid7()), shelf)
    async with inventory(engine) as work:
        for location in (lab, shelf):
            await work.locations.add(location)
        for lot in (stocked, fresh, elsewhere):
            await work.lots.add(lot)
        received = StockBalance.opening(stocked.id).apply(
            a_movement(stocked, MovementKind.RECEIVE, 12)
        )
        await work.balances.put(received)
        await work.balances.put(
            StockBalance.opening(elsewhere.id).apply(a_movement(elsewhere, MovementKind.RECEIVE, 3))
        )
        await work.commit()

    async with inventory(engine) as work:
        with counting(engine) as statements:
            held = await work.balances.at_location(lab.id)
    async with inventory(engine, WorkspaceId(uuid7())) as theirs:
        unseen = await theirs.balances.at_location(lab.id)

    assert [(lot.lot_id, int(lot.on_hand), int(lot.reserved)) for lot in held] == sorted(
        [(stocked.id, 12, 0), (fresh.id, 0, 0)]
    )
    assert {lot.part_id for lot in held} == {stocked.part_id, fresh.part_id}
    assert len(statements) == 1, statements
    assert unseen == []


async def test_the_stocked_parts_come_in_one_grouped_query(engine: AsyncEngine) -> None:
    # The parts list's stock filter: a part counts once its lots hold stock between them,
    # never for a lot used up or one with no balance yet, never for another workspace.
    lab = a_location("WX-L-0001", "Lab")
    shelf = a_location("WX-L-0002", "Shelf")
    spread = PartId(uuid7())
    used_up = PartId(uuid7())
    shelved = a_lot(spread, shelf)
    fresh = a_lot(spread, lab)
    emptied = a_lot(used_up, lab)
    async with inventory(engine) as work:
        for location in (lab, shelf):
            await work.locations.add(location)
        for lot in (shelved, fresh, emptied):
            await work.lots.add(lot)
        await work.commit()
    received = StockBalance.opening(shelved.id).apply(a_movement(shelved, MovementKind.RECEIVE, 4))
    taken = StockBalance.opening(emptied.id).apply(a_movement(emptied, MovementKind.RECEIVE, 2))
    await put_in_its_own_transaction(engine, received)
    await put_in_its_own_transaction(engine, taken)
    await put_in_its_own_transaction(
        engine, taken.apply(a_movement(emptied, MovementKind.ADJUST, -2))
    )

    async with inventory(engine) as work:
        with counting(engine) as statements:
            stocked = await work.balances.stocked_parts()
    async with inventory(engine, WorkspaceId(uuid7())) as theirs:
        unseen = await theirs.balances.stocked_parts()

    assert stocked == {spread}
    assert len(statements) == 1, statements
    assert unseen == set()


@pytest.mark.parametrize("count", [1, 30])
async def test_available_stock_comes_in_one_grouped_query(engine: AsyncEngine, count: int) -> None:
    # 09's requirements 6.2 and 12.3: one statement whatever the number of parts, the same as
    # on_hand while nothing is reserved, and another workspace's lots of the same part never
    # summed into this one's.
    lab = a_location("WX-L-0001", "Lab")
    parts = [PartId(uuid7()) for _ in range(count)]
    lots = [a_lot(part, lab) for part in parts]
    theirs = WorkspaceId(uuid7())
    their_lab = Location(
        LocationId(uuid7()), theirs, None, ShortCode("WX-L-0001"), LocationName("Lab"), NOW
    )
    their_lot = StockLot(StockLotId(uuid7()), theirs, parts[0], their_lab.id, NOW)
    async with inventory(engine) as work:
        await work.locations.add(lab)
        for index, lot in enumerate(lots, start=1):
            await work.lots.add(lot)
            await work.balances.put(
                StockBalance.opening(lot.id).apply(a_movement(lot, MovementKind.RECEIVE, index))
            )
        await work.commit()
    async with inventory(engine, theirs) as work:
        await work.locations.add(their_lab)
        await work.lots.add(their_lot)
        await work.balances.put(
            StockBalance.opening(their_lot.id).apply(
                a_movement(their_lot, MovementKind.RECEIVE, 500)
            )
        )
        await work.commit()

    async with inventory(engine) as work:
        with counting(engine) as statements:
            available = await work.balances.available_by_part([*parts, PartId(uuid7())])
        on_hand = await work.balances.totals_by_part(parts)

    assert available == {part: index for index, part in enumerate(parts, start=1)}
    assert available == on_hand
    assert len(statements) == 1, statements


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


def a_revision_movement(
    lot: StockLot, kind: MovementKind, change: int, revision_id: RevisionId
) -> StockMovement:
    """A movement naming a revision — the four v0.5.0 kinds — for the holdings queries."""
    return StockMovement(
        StockMovementId(uuid7()),
        BENCH,
        lot.id,
        kind,
        change,
        None,
        None,
        None,
        revision_id,
        NOW,
    )


async def test_lots_at_finds_each_parts_return_lot_at_a_location(engine: AsyncEngine) -> None:
    # The return lots of a dismantle: each part's lot at the chosen location, the ones that
    # exist, in one query; a part with none is absent (requirement 6.2).
    lab = a_location("WX-L-0001", "Lab")
    shelf = a_location("WX-L-0002", "Shelf")
    resistor = PartId(uuid7())
    board = PartId(uuid7())
    absent = PartId(uuid7())
    lab_resistor = a_lot(resistor, lab)
    lab_board = a_lot(board, lab)
    shelf_resistor = a_lot(resistor, shelf)  # the same part, a different location
    async with inventory(engine) as work:
        await work.locations.add(lab)
        await work.locations.add(shelf)
        for lot in (lab_resistor, lab_board, shelf_resistor):
            await work.lots.add(lot)
        await work.commit()

    async with inventory(engine) as work:
        found = await work.lots.at(lab.id, [resistor, board, absent])

    assert {part: lot.id for part, lot in found.items()} == {
        resistor: lab_resistor.id,
        board: lab_board.id,
    }


async def test_sums_of_revision_group_a_revisions_rows(engine: AsyncEngine) -> None:
    # A revision's changes grouped by lot, part, location and kind, in one query over the
    # partial index (requirement 8.5). Two RESERVEs on one lot sum; another lot is its own row.
    lab = a_location("WX-L-0001", "Lab")
    shelf = a_location("WX-L-0002", "Shelf")
    part = PartId(uuid7())
    lab_lot = a_lot(part, lab)
    shelf_lot = a_lot(part, shelf)
    revision = RevisionId(uuid7())
    async with inventory(engine) as work:
        await work.locations.add(lab)
        await work.locations.add(shelf)
        await work.lots.add(lab_lot)
        await work.lots.add(shelf_lot)
        await work.ledger.append(a_revision_movement(lab_lot, MovementKind.RESERVE, 3, revision))
        await work.ledger.append(a_revision_movement(lab_lot, MovementKind.CONSUME, -3, revision))
        await work.ledger.append(a_revision_movement(shelf_lot, MovementKind.RESERVE, 1, revision))
        # Another revision's row on the same lot stays out of this revision's sums.
        await work.ledger.append(
            a_revision_movement(lab_lot, MovementKind.RESERVE, 5, RevisionId(uuid7()))
        )
        await work.commit()

    async with inventory(engine) as work:
        with counting(engine) as statements:
            sums = await work.ledger.sums_of_revision(revision)

    assert len(statements) == 1, statements
    by_lot_kind = {(s.lot_id, s.kind): s.change for s in sums}
    assert by_lot_kind == {
        (lab_lot.id, MovementKind.RESERVE): 3,
        (lab_lot.id, MovementKind.CONSUME): -3,
        (shelf_lot.id, MovementKind.RESERVE): 1,
    }
    # Each sum carries its lot's part and its location code, for the holdings read.
    lab_reserve = next(s for s in sums if s.lot_id == lab_lot.id and s.kind is MovementKind.RESERVE)
    assert (lab_reserve.part_id, lab_reserve.location_code) == (part, "WX-L-0001")


async def test_sums_of_part_group_each_revisions_rows(engine: AsyncEngine) -> None:
    # One part's rows grouped by revision (requirement 10.4), in one query; only rows naming a
    # revision count, and another part's rows stay out.
    lab = a_location("WX-L-0001", "Lab")
    part = PartId(uuid7())
    other = PartId(uuid7())
    lot = a_lot(part, lab)
    other_lot = a_lot(other, lab)
    first = RevisionId(uuid7())
    second = RevisionId(uuid7())
    async with inventory(engine) as work:
        await work.locations.add(lab)
        await work.lots.add(lot)
        await work.lots.add(other_lot)
        await work.ledger.append(a_revision_movement(lot, MovementKind.RESERVE, 2, first))
        await work.ledger.append(a_revision_movement(lot, MovementKind.RESERVE, 4, second))
        await work.ledger.append(a_revision_movement(other_lot, MovementKind.RESERVE, 9, first))
        await work.commit()

    async with inventory(engine) as work:
        with counting(engine) as statements:
            by_revision = await work.ledger.sums_of_part(part)

    assert len(statements) == 1, statements
    reserved = {
        revision: sum(s.change for s in sums if s.kind is MovementKind.RESERVE)
        for revision, sums in by_revision.items()
    }
    assert reserved == {first: 2, second: 4}


async def test_sums_of_holdings_group_every_revisions_rows(engine: AsyncEngine) -> None:
    # Every part's rows grouped by revision (18-dashboard, decision 1), in one query; a row
    # naming no revision, a receive, stays out.
    lab = a_location("WX-L-0001", "Lab")
    part = PartId(uuid7())
    other = PartId(uuid7())
    lot = a_lot(part, lab)
    other_lot = a_lot(other, lab)
    first = RevisionId(uuid7())
    second = RevisionId(uuid7())
    async with inventory(engine) as work:
        await work.locations.add(lab)
        await work.lots.add(lot)
        await work.lots.add(other_lot)
        await work.ledger.append(a_movement(lot, MovementKind.RECEIVE, 10))
        await work.ledger.append(a_revision_movement(lot, MovementKind.RESERVE, 2, first))
        await work.ledger.append(a_revision_movement(other_lot, MovementKind.RESERVE, 9, first))
        await work.ledger.append(a_revision_movement(lot, MovementKind.RESERVE, 4, second))
        await work.ledger.append(a_revision_movement(lot, MovementKind.CONSUME, -4, second))
        await work.commit()

    async with inventory(engine) as work:
        with counting(engine) as statements:
            by_revision = await work.ledger.sums_of_holdings()

    assert len(statements) == 1, statements
    assert {
        revision: {(s.part_id, s.kind, s.change) for s in sums}
        for revision, sums in by_revision.items()
    } == {
        first: {(part, MovementKind.RESERVE, 2), (other, MovementKind.RESERVE, 9)},
        second: {(part, MovementKind.RESERVE, 4), (part, MovementKind.CONSUME, -4)},
    }


async def test_balance_lock_reads_lots_with_part_and_code_in_lot_id_order(
    engine: AsyncEngine,
) -> None:
    # FOR UPDATE in lot-id order, each with its part and location code, in one query (10).
    lab = a_location("WX-L-0001", "Lab")
    shelf = a_location("WX-L-0002", "Shelf")
    part = PartId(uuid7())
    lot_one = a_lot(part, lab)
    lot_two = a_lot(part, shelf)
    async with inventory(engine) as work:
        await work.locations.add(lab)
        await work.locations.add(shelf)
        for lot, qty in ((lot_one, 10), (lot_two, 4)):
            await work.lots.add(lot)
            await work.balances.put(
                StockBalance.opening(lot.id).apply(a_movement(lot, MovementKind.RECEIVE, qty))
            )
        await work.commit()

    async with inventory(engine) as work:
        with counting(engine) as statements:
            locked = await work.balances.lock(sorted([lot_two.id, lot_one.id]))

    assert len(statements) == 1, statements
    assert [row.lot.id for row in locked] == sorted([lot_one.id, lot_two.id])
    on_hand = {row.lot.id: int(row.balance.on_hand) for row in locked}
    assert on_hand == {lot_one.id: 10, lot_two.id: 4}
    assert all(row.lot.part_id == part for row in locked)


async def test_balance_lock_opens_a_lot_with_no_balance_yet(engine: AsyncEngine) -> None:
    # A fresh return lot has no balance row: lock still returns it, at its opening balance, so
    # the caller writes the first put (decision 10).
    lab = a_location("WX-L-0001", "Lab")
    part = PartId(uuid7())
    lot = a_lot(part, lab)
    async with inventory(engine) as work:
        await work.locations.add(lab)
        await work.lots.add(lot)
        await work.commit()

    async with inventory(engine) as work:
        locked = await work.balances.lock([lot.id])

    assert len(locked) == 1
    assert (int(locked[0].balance.on_hand), locked[0].balance.version) == (0, 0)


async def test_balance_lock_by_part_locks_every_lot_of_the_parts(engine: AsyncEngine) -> None:
    lab = a_location("WX-L-0001", "Lab")
    shelf = a_location("WX-L-0002", "Shelf")
    part = PartId(uuid7())
    other = PartId(uuid7())
    lab_lot = a_lot(part, lab)
    shelf_lot = a_lot(part, shelf)
    other_lot = a_lot(other, lab)
    async with inventory(engine) as work:
        await work.locations.add(lab)
        await work.locations.add(shelf)
        for lot in (lab_lot, shelf_lot, other_lot):
            await work.lots.add(lot)
            await work.balances.put(
                StockBalance.opening(lot.id).apply(a_movement(lot, MovementKind.RECEIVE, 5))
            )
        await work.commit()

    async with inventory(engine) as work:
        locked = await work.balances.lock_by_part([part])

    # Both of the part's lots, in lot-id order, and not the other part's.
    assert [row.lot.id for row in locked] == sorted([lab_lot.id, shelf_lot.id])


async def test_the_new_lot_and_balance_reads_answer_empty_for_empty_input(
    engine: AsyncEngine,
) -> None:
    async with inventory(engine) as work:
        assert await work.lots.at(LocationId(uuid7()), []) == {}
        assert await work.balances.lock([]) == []
        assert await work.balances.lock_by_part([]) == []
