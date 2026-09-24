import asyncio
import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from click.testing import CliRunner
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from wiredex.bootstrap.cli import cli

pytestmark = pytest.mark.integration


def run(database_url: str, *arguments: str) -> str:
    result = CliRunner().invoke(cli, list(arguments), env={"WIREDEX_DATABASE_URL": database_url})
    assert result.exit_code == 0, result.output
    return result.output


async def query(database_url: str, sql: str) -> list[tuple[object, ...]]:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            result = await connection.execute(text(sql))
            return [tuple(row) for row in result] if result.returns_rows else []
    finally:
        await engine.dispose()


@pytest.fixture
def database(migrated_database_url: str, app_database_url: str) -> Iterator[str]:
    """The app role's URL, like production; the tables are emptied afterwards."""
    yield app_database_url
    asyncio.run(
        query(migrated_database_url, "TRUNCATE users, workspaces, memberships, sessions CASCADE")
    )


def test_invite_creates_a_guest_in_a_demo_bench_and_prints_the_password_once(
    database: str,
) -> None:
    output = run(database, "demo", "invite", "--email", "Friend@Example.com", "--expires", "2w")

    assert re.search(r"Invited friend@example.com until \d{4}-\d\d-\d\d \d\d:\d\d UTC", output)
    password = re.search(r"Password, shown only now: (\S+)", output)
    assert password is not None
    assert len(password[1]) == 16
    [(expires_at, kind, role)] = asyncio.run(
        query(
            database,
            "SELECT u.expires_at, w.kind, m.role FROM users u"
            " JOIN memberships m ON m.user_id = u.id JOIN workspaces w ON w.id = m.workspace_id",
        )
    )
    assert (kind, role) == ("demo", "guest")
    assert isinstance(expires_at, datetime)
    assert expires_at - datetime.now(UTC) > timedelta(days=13)


def test_reset_removes_guests_whose_access_ended(database: str, migrated_database_url: str) -> None:
    run(database, "demo", "invite", "--email", "gone@example.com", "--expires", "1h")
    run(database, "demo", "invite", "--email", "still-here@example.com")
    asyncio.run(
        query(
            migrated_database_url,
            "UPDATE users SET expires_at = now() - interval '1 minute'"
            " WHERE email = 'gone@example.com'",
        )
    )

    output = run(database, "demo", "reset")

    assert "Removed 1 expired guest account(s)." in output
    assert asyncio.run(query(database, "SELECT email FROM users")) == [("still-here@example.com",)]
    assert asyncio.run(query(database, "SELECT count(*) FROM workspaces")) == [(1,)]
