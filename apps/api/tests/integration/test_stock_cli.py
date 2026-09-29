import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import uuid7

import pytest
from click.testing import CliRunner
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from support.identity import ManualClock, NewIds
from wiredex.bootstrap.cli import cli
from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.settings import Environment, Settings
from wiredex.inventory.application.builds import LotTake, RevisionStock
from wiredex.inventory.domain.ledger import StockMovement
from wiredex.inventory.domain.location import Location
from wiredex.inventory.domain.lot import StockBalance, StockLot
from wiredex.inventory.domain.values import (
    LocationId,
    LocationName,
    MoveGroupId,
    MovementKind,
    MovementReason,
    PartId,
    RevisionId,
    ShortCode,
    StockLotId,
    StockMovementId,
    WorkspaceId,
)
from wiredex.inventory.infrastructure.unit_of_work import (
    SqlInventoryRepositories,
    SqlInventoryUnitOfWork,
)

pytestmark = pytest.mark.integration


def run(database_url: str, *arguments: str, standard_input: str | None = None) -> str:
    env = {"WIREDEX_DATABASE_URL": database_url}
    result = CliRunner().invoke(cli, list(arguments), input=standard_input, env=env)
    assert result.exit_code == 0, result.output
    return result.output


async def query(database_url: str, sql: str, **parameters: object) -> list[tuple[object, ...]]:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            result = await connection.execute(text(sql), parameters)
            return [tuple(row) for row in result] if result.returns_rows else []
    finally:
        await engine.dispose()


@pytest.fixture
def database(migrated_database_url: str, app_database_url: str) -> Iterator[str]:
    """The app role's URL, like production; the tables are emptied afterwards."""
    yield app_database_url
    asyncio.run(
        query(
            migrated_database_url,
            "TRUNCATE users, workspaces, memberships, sessions, categories,"
            " attribute_definitions, part_definitions, files, attachments,"
            " locations, short_code_counters, stock_lots, stock_movements, stock_balances,"
            " units, projects, revisions CASCADE",
        )
    )


def _seed_inventory(database: str, email: str) -> None:
    """A demo bench with the sample locations and stock, through the real reset (8.6)."""
    run(database, "demo", "invite", "--email", email)
    run(database, "demo", "reset")


def test_rebuild_restores_a_balance_tampered_below_its_ledger(
    database: str, migrated_database_url: str
) -> None:
    """Requirement 5.2/5.3: a balance a bug wrote wrong is rebuilt from the ledger, which is
    the source of truth, back to the total of the lot's movements."""
    _seed_inventory(database, "guest@example.com")
    # A balance the projection distrusts: knock one lot's on_hand down to a lie. The lot must
    # hold nothing reserved, since the demo reset reserves the greenhouse's parts (10's
    # requirement 12): a tampered available of 1 would break the derived-available CHECK on a
    # lot whose reserved is non-zero.
    [(lot_id, real_on_hand)] = asyncio.run(
        query(
            migrated_database_url,
            "SELECT lot_id, on_hand FROM stock_balances WHERE reserved = 0"
            " ORDER BY on_hand DESC LIMIT 1",
        )
    )
    assert isinstance(real_on_hand, int)
    assert real_on_hand > 0
    asyncio.run(
        query(
            migrated_database_url,
            "UPDATE stock_balances SET on_hand = 1, available = 1 WHERE lot_id = :lot",
            lot=lot_id,
        )
    )

    output = run(database, "stock", "rebuild")

    assert "Rebuilt stock balances in 1 workspace(s)." in output
    # The balance equals the sum of its lot's ledger again, available with it.
    assert asyncio.run(
        query(
            migrated_database_url,
            "SELECT on_hand, available FROM stock_balances WHERE lot_id = :lot",
            lot=lot_id,
        )
    ) == [(real_on_hand, real_on_hand)]
    # Every balance now equals its per-kind fold of the ledger, on hand and reserved agreeing
    # (requirement 8.4): the demo's RESERVE rows count toward reserved, not on hand.
    assert asyncio.run(query(migrated_database_url, _BALANCES_DISAGREEING_BY_KIND)) == [(0,)]


def test_rebuild_runs_per_workspace_under_isolation(
    database: str, migrated_database_url: str
) -> None:
    """Requirement 5.3: rebuild sweeps every workspace, each in its own transaction under its
    own isolation, so one bench's tampered balance is repaired without disturbing another's."""
    _seed_inventory(database, "first@example.com")
    _seed_inventory(database, "second@example.com")
    # Two workspaces, each with its own sample stock; tamper with a balance in one of them.
    # The lot must hold nothing reserved (the demo reserves the greenhouse's parts, 10's
    # requirement 12), so a tampered available of 0 keeps the derived-available CHECK.
    [(victim_lot, real_on_hand)] = asyncio.run(
        query(
            migrated_database_url,
            "SELECT lot_id, on_hand FROM stock_balances WHERE reserved = 0"
            " ORDER BY on_hand DESC LIMIT 1",
        )
    )
    assert isinstance(real_on_hand, int)
    asyncio.run(
        query(
            migrated_database_url,
            "UPDATE stock_balances SET on_hand = 0, available = 0 WHERE lot_id = :lot",
            lot=victim_lot,
        )
    )

    output = run(database, "stock", "rebuild")

    assert "Rebuilt stock balances in 2 workspace(s)." in output
    # The tampered balance is back, and across both benches no balance disagrees with its
    # ledger: each workspace was rebuilt from its own movements.
    assert asyncio.run(
        query(
            migrated_database_url,
            "SELECT on_hand FROM stock_balances WHERE lot_id = :lot",
            lot=victim_lot,
        )
    ) == [(real_on_hand,)]
    assert asyncio.run(query(migrated_database_url, _BALANCES_DISAGREEING_BY_KIND)) == [(0,)]


# The projection equals the ledger folded by kind: on_hand moves with RECEIVE, ADJUST, MOVE,
# CONSUME and RETURN; reserved with RESERVE, RELEASE and CONSUME (requirement 8.3). A rebuild
# over all seven kinds must reproduce both counts (requirement 8.4).
_ON_HAND_MOVING = "('RECEIVE', 'ADJUST', 'MOVE', 'CONSUME', 'RETURN')"
_RESERVED_MOVING = "('RESERVE', 'RELEASE', 'CONSUME')"
_BALANCES_DISAGREEING_BY_KIND = (
    # The IN lists are literal kind constants, not input: not an injection vector.
    "SELECT count(*) FROM stock_balances b WHERE b.on_hand <> ("  # noqa: S608
    f" SELECT coalesce(sum(m.change), 0) FROM stock_movements m WHERE m.lot_id = b.lot_id"
    f" AND m.kind IN {_ON_HAND_MOVING})"
    " OR b.reserved <> ("
    f" SELECT coalesce(sum(m.change), 0) FROM stock_movements m WHERE m.lot_id = b.lot_id"
    f" AND m.kind IN {_RESERVED_MOVING})"
)

_SEVEN_KINDS_NOW = datetime(2026, 9, 28, 12, tzinfo=UTC)


def _movement(  # noqa: PLR0913 — a test helper mirroring StockMovement's own fields
    bench: WorkspaceId,
    lot_id: StockLotId,
    kind: MovementKind,
    change: int,
    *,
    reason: MovementReason | None = None,
    move_group: MoveGroupId | None = None,
) -> StockMovement:
    return StockMovement(
        StockMovementId(uuid7()),
        bench,
        lot_id,
        kind,
        change,
        reason,
        None,
        move_group,
        None,
        _SEVEN_KINDS_NOW,
    )


async def _seed_receive_adjust_move(
    work: SqlInventoryUnitOfWork, bench: WorkspaceId, part: PartId, drawer_id: LocationId
) -> tuple[StockLot, Location]:
    """RECEIVE 20, ADJUST down 2, then MOVE 5 onto a fresh shelf: the three v0.4.0 kinds, folded
    live into two lots' balances, so the projection starts agreeing with its ledger."""
    shelf = Location(
        LocationId(uuid7()),
        bench,
        None,
        ShortCode("WX-L-9002"),
        LocationName("Tray"),
        _SEVEN_KINDS_NOW,
    )
    lot = StockLot(StockLotId(uuid7()), bench, part, drawer_id, _SEVEN_KINDS_NOW)
    shelf_lot = StockLot(StockLotId(uuid7()), bench, part, shelf.id, _SEVEN_KINDS_NOW)
    await work.locations.add(shelf)
    await work.lots.add(lot)
    await work.lots.add(shelf_lot)
    receive = _movement(bench, lot.id, MovementKind.RECEIVE, 20)
    await work.ledger.append(receive)
    after_receive = StockBalance.opening(lot.id).apply(receive)
    await work.balances.put(after_receive)
    adjust = _movement(bench, lot.id, MovementKind.ADJUST, -2, reason=MovementReason.RECOUNT)
    await work.ledger.append(adjust)
    after_adjust = after_receive.apply(adjust)
    await work.balances.put(after_adjust)
    group = MoveGroupId(uuid7())
    move_out = _movement(bench, lot.id, MovementKind.MOVE, -5, move_group=group)
    await work.ledger.append(move_out)
    await work.balances.put(after_adjust.apply(move_out))
    move_in = _movement(bench, shelf_lot.id, MovementKind.MOVE, 5, move_group=group)
    await work.ledger.append(move_in)
    await work.balances.put(StockBalance.opening(shelf_lot.id).apply(move_in))
    return lot, shelf


def _revision_stock(work: SqlInventoryUnitOfWork, bench: WorkspaceId) -> RevisionStock:
    """`RevisionStock` on the unit of work's session, as `bootstrap/build.py` will bind it."""
    return RevisionStock(
        SqlInventoryRepositories(work.session, bench),
        bench,
        ManualClock(_SEVEN_KINDS_NOW),
        NewIds(),
    )


async def _write_all_seven_kinds(
    database: str, bench: WorkspaceId, part: PartId, revision: RevisionId
) -> None:
    """A workspace's ledger with every kind, written over the app role like production: the
    three v0.4.0 kinds, then a reserve and its cancel (RESERVE, RELEASE) and a reserve, build
    and dismantle (RESERVE, CONSUME, RETURN), each in its own committed transaction."""
    settings = Settings(environment=Environment.TEST, database_url=SecretStr(database))
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    try:
        drawer = Location(
            LocationId(uuid7()),
            bench,
            None,
            ShortCode("WX-L-9001"),
            LocationName("Bin"),
            _SEVEN_KINDS_NOW,
        )
        async with SqlInventoryUnitOfWork(sessions, bench) as work:
            await work.locations.add(drawer)
            lot, shelf = await _seed_receive_adjust_move(work, bench, part, drawer.id)
            await work.commit()

        cancelled = RevisionId(uuid7())
        async with SqlInventoryUnitOfWork(sessions, bench) as work:
            stock = _revision_stock(work, bench)
            locked = await stock.available([part], [])
            await stock.reserve(locked, cancelled, [LotTake(lot.id, 3, ())])
            await work.commit()
        async with SqlInventoryUnitOfWork(sessions, bench) as work:
            await _revision_stock(work, bench).release(cancelled)
            await work.commit()
        async with SqlInventoryUnitOfWork(sessions, bench) as work:
            stock = _revision_stock(work, bench)
            locked = await stock.available([part], [])
            await stock.reserve(locked, revision, [LotTake(lot.id, 4, ())])
            await work.commit()
        async with SqlInventoryUnitOfWork(sessions, bench) as work:
            await _revision_stock(work, bench).consume(revision)
            await work.commit()
        async with SqlInventoryUnitOfWork(sessions, bench) as work:
            await _revision_stock(work, bench).return_to(revision, shelf.id)
            await work.commit()
    finally:
        await engine.dispose()


def test_rebuild_folds_all_seven_kinds_including_reserved(
    database: str, migrated_database_url: str
) -> None:
    """Requirement 8.4: a workspace whose ledger holds all seven kinds — a revision reserved,
    cancelled, reserved again, built and dismantled, alongside receipts, an adjust and a move —
    rebuilds to the balances written as the movements happened, reserved included.

    The revision kinds are written through `RevisionStock`, inventory's half of a build
    transition, over the app role like production. Then both counts on a balance are tampered
    and the rebuild restores every balance to its per-kind fold of the ledger.
    """
    _seed_inventory(database, "guest@example.com")
    [(workspace_raw,)] = asyncio.run(
        query(migrated_database_url, "SELECT id FROM workspaces LIMIT 1")
    )
    bench = WorkspaceId(workspace_raw)  # type: ignore[arg-type]
    part = PartId(uuid7())
    revision = RevisionId(uuid7())

    asyncio.run(_write_all_seven_kinds(database, bench, part, revision))

    # Every one of the seven kinds is now in this workspace's ledger.
    [(kinds,)] = asyncio.run(
        query(
            migrated_database_url,
            "SELECT count(DISTINCT kind) FROM stock_movements WHERE workspace_id = :w",
            w=str(bench),
        )
    )
    assert kinds == 7, kinds
    # Before tampering, the projection already agrees with its per-kind fold.
    assert asyncio.run(query(migrated_database_url, _BALANCES_DISAGREEING_BY_KIND)) == [(0,)]

    # Tamper both counts on the built lot: a bug wrote nonsense over on_hand and reserved.
    asyncio.run(
        query(
            migrated_database_url,
            "UPDATE stock_balances SET on_hand = 99, reserved = 7, available = 92"
            " WHERE lot_id = (SELECT lot_id FROM stock_movements WHERE kind = 'CONSUME' LIMIT 1)",
        )
    )

    output = run(database, "stock", "rebuild")

    assert "Rebuilt stock balances in 1 workspace(s)." in output
    # Every balance again equals its per-kind fold of the ledger, reserved included.
    assert asyncio.run(query(migrated_database_url, _BALANCES_DISAGREEING_BY_KIND)) == [(0,)]
