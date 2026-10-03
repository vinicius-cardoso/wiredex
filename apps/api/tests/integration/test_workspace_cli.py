"""`wiredex workspace clear`: an account's workspace emptied of every module's data."""

import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest
from click.testing import CliRunner
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from wiredex.bootstrap.cli import cli

pytestmark = pytest.mark.integration


@pytest.fixture
def database(migrated_database_url: str, app_database_url: str) -> Iterator[str]:
    """The app role's URL, like production; the tables are emptied afterwards."""
    yield app_database_url
    asyncio.run(_empty(migrated_database_url))


def invoke(database_url: str, files_dir: Path, *arguments: str) -> tuple[int, str]:
    env = {
        "WIREDEX_DATABASE_URL": database_url,
        # Keep ClearWorkspace off the real apps/api/.files folder.
        "WIREDEX_FILE_STORE": "local",
        "WIREDEX_FILES_DIR": str(files_dir),
    }
    result = CliRunner().invoke(cli, list(arguments), env=env)
    return result.exit_code, result.output


async def _execute(database_url: str, sql: str, **values: object) -> list[tuple[object, ...]]:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            result = await connection.execute(text(sql), values)
            return [tuple(row) for row in result] if result.returns_rows else []
    finally:
        await engine.dispose()


_WORKSPACE_TABLES = (
    "SELECT table_name FROM information_schema.columns"
    " WHERE table_schema = 'public' AND column_name = 'workspace_id'"
)


async def _empty(owner_url: str) -> None:
    """Every workspace table and identity's own, whatever a later migration adds."""
    tables = [str(table) for (table,) in await _execute(owner_url, _WORKSPACE_TABLES)]
    listed = ", ".join(sorted({*tables, "users", "workspaces", "sessions"}))
    await _execute(owner_url, f"TRUNCATE {listed} CASCADE")


async def rows_by_table(owner_url: str, email: str) -> dict[str, int]:
    """How many rows each workspace table holds for the account's workspace, identity's own
    aside. Read by the schema owner, whom row-level security doesn't narrow."""
    [(workspace_id,)] = await _execute(
        owner_url,
        "SELECT m.workspace_id FROM memberships m JOIN users u ON u.id = m.user_id"
        " WHERE u.email = :email",
        email=email,
    )
    counts: dict[str, int] = {}
    for (table,) in await _execute(owner_url, _WORKSPACE_TABLES):
        if table == "memberships":
            continue
        # A table's name can't be bound, and these come from the catalog, not from input.
        counting = f"SELECT count(*) FROM {table} WHERE workspace_id = :workspace"  # noqa: S608
        [(count,)] = await _execute(owner_url, counting, workspace=workspace_id)
        counts[str(table)] = int(str(count))
    return counts


def test_clear_empties_every_module_of_the_accounts_workspace_and_no_other(
    database: str, migrated_database_url: str, tmp_path: Path
) -> None:
    # A demo bench is the quickest workspace with data in every module.
    for guest in ("first@example.com", "second@example.com"):
        code, output = invoke(database, tmp_path, "demo", "invite", "--email", guest)
        assert code == 0, output
    before = asyncio.run(rows_by_table(migrated_database_url, "first@example.com"))
    assert before["part_definitions"] > 0
    assert before["stock_movements"] > 0
    assert before["projects"] > 0
    assert before["firmware"] > 0
    untouched = asyncio.run(rows_by_table(migrated_database_url, "second@example.com"))

    code, output = invoke(
        database, tmp_path, "workspace", "clear", "--email", "first@example.com", "--yes"
    )

    assert code == 0, output
    assert "Emptied 1 workspace(s) of first@example.com." in output
    after = asyncio.run(rows_by_table(migrated_database_url, "first@example.com"))
    assert {table: count for table, count in after.items() if count} == {}
    assert asyncio.run(rows_by_table(migrated_database_url, "second@example.com")) == untouched


def test_clear_asks_first_and_stops_on_no(
    database: str, migrated_database_url: str, tmp_path: Path
) -> None:
    code, output = invoke(database, tmp_path, "demo", "invite", "--email", "first@example.com")
    assert code == 0, output
    before = asyncio.run(rows_by_table(migrated_database_url, "first@example.com"))

    result = CliRunner().invoke(
        cli,
        ["workspace", "clear", "--email", "first@example.com"],
        input="n\n",
        env={"WIREDEX_DATABASE_URL": database},
    )

    assert result.exit_code != 0
    assert asyncio.run(rows_by_table(migrated_database_url, "first@example.com")) == before


def test_clear_refuses_an_email_no_account_uses(database: str, tmp_path: Path) -> None:
    code, output = invoke(
        database, tmp_path, "workspace", "clear", "--email", "nobody@example.com", "--yes"
    )

    assert code != 0
    assert "no account uses nobody@example.com" in output
