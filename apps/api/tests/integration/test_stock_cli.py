import asyncio
from collections.abc import Iterator

import pytest
from click.testing import CliRunner
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from wiredex.bootstrap.cli import cli

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
            " locations, short_code_counters, stock_lots, stock_movements, stock_balances"
            " CASCADE",
        )
    )


def _seed_inventory(database: str, email: str) -> None:
    """A demo bench with the sample locations and stock, through the real reset (8.6)."""
    run(database, "demo", "invite", "--email", email)
    run(database, "demo", "reset")


# No balance may disagree with the sum of its lot's movements: the projection equals the
# ledger it is folded from (requirement 5.1).
_BALANCES_DISAGREEING = (
    "SELECT count(*) FROM stock_balances b WHERE b.on_hand <> ("
    " SELECT coalesce(sum(m.change), 0) FROM stock_movements m WHERE m.lot_id = b.lot_id)"
)


def test_rebuild_restores_a_balance_tampered_below_its_ledger(
    database: str, migrated_database_url: str
) -> None:
    """Requirement 5.2/5.3: a balance a bug wrote wrong is rebuilt from the ledger, which is
    the source of truth, back to the total of the lot's movements."""
    _seed_inventory(database, "guest@example.com")
    # A balance the projection distrusts: knock one lot's on_hand down to a lie.
    [(lot_id, real_on_hand)] = asyncio.run(
        query(
            migrated_database_url,
            "SELECT lot_id, on_hand FROM stock_balances ORDER BY on_hand DESC LIMIT 1",
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
    # Every balance now equals the sum of its lot's movements, projection and ledger agreeing.
    assert asyncio.run(query(migrated_database_url, _BALANCES_DISAGREEING)) == [(0,)]


def test_rebuild_runs_per_workspace_under_isolation(
    database: str, migrated_database_url: str
) -> None:
    """Requirement 5.3: rebuild sweeps every workspace, each in its own transaction under its
    own isolation, so one bench's tampered balance is repaired without disturbing another's."""
    _seed_inventory(database, "first@example.com")
    _seed_inventory(database, "second@example.com")
    # Two workspaces, each with its own sample stock; tamper with a balance in one of them.
    [(victim_lot, real_on_hand)] = asyncio.run(
        query(
            migrated_database_url,
            "SELECT lot_id, on_hand FROM stock_balances ORDER BY on_hand DESC LIMIT 1",
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
    assert asyncio.run(query(migrated_database_url, _BALANCES_DISAGREEING)) == [(0,)]
