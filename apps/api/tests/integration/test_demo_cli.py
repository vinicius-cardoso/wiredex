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


def run(database_url: str, *arguments: str, standard_input: str | None = None) -> str:
    result = CliRunner().invoke(
        cli,
        list(arguments),
        input=standard_input,
        env={"WIREDEX_DATABASE_URL": database_url},
    )
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
        query(
            migrated_database_url,
            "TRUNCATE users, workspaces, memberships, sessions,"
            " categories, attribute_definitions, part_definitions CASCADE",
        )
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


def test_reset_restores_the_sample_catalog_in_demo_benches_only(
    database: str, migrated_database_url: str
) -> None:
    """The catalog is queried as the schema owner: row-level security hides it otherwise."""
    run(
        database,
        "users",
        "create",
        "--email",
        "owner@example.com",
        "--name",
        "Owner",
        "--password-stdin",
        standard_input="correct horse battery\n",
    )
    run(database, "demo", "invite", "--email", "guest@example.com")

    output = run(database, "demo", "reset")

    assert "Restored the sample catalog of 1 demo workspace(s)." in output
    assert asyncio.run(
        query(migrated_database_url, "SELECT name FROM categories ORDER BY name")
    ) == [("Capacitors",), ("Passives",), ("Resistors",)]
    # Only the guest's bench: the owner's workspace is left exactly as it was.
    assert asyncio.run(
        query(
            migrated_database_url,
            "SELECT DISTINCT w.kind FROM workspaces w"
            " JOIN part_definitions p ON p.workspace_id = w.id",
        )
    ) == [("demo",)]
    # 4k7 typed, 4700 stored: compared as a number, so neither side's spelling decides it.
    assert asyncio.run(
        query(
            migrated_database_url,
            "SELECT (attributes->>'resistance')::numeric = 4700 FROM part_definitions"
            " WHERE mpn = 'RC0805FR-074K7L'",
        )
    ) == [(True,)]


def test_reset_puts_back_what_a_guest_changed(database: str, migrated_database_url: str) -> None:
    run(database, "demo", "invite", "--email", "guest@example.com")
    run(database, "demo", "reset")
    asyncio.run(query(migrated_database_url, "DELETE FROM part_definitions"))
    asyncio.run(
        query(
            migrated_database_url,
            "UPDATE categories SET name = 'Theirs' WHERE name = 'Passives'",
        )
    )

    run(database, "demo", "reset")

    assert asyncio.run(query(migrated_database_url, "SELECT count(*) FROM part_definitions")) == [
        (5,)
    ]
    assert asyncio.run(
        query(migrated_database_url, "SELECT count(*) FROM categories WHERE name = 'Theirs'")
    ) == [(0,)]


def test_a_new_guest_finds_the_sample_catalog_at_once(
    database: str, migrated_database_url: str
) -> None:
    """No waiting for the nightly reset: the invite itself seeds the new bench."""
    run(database, "demo", "invite", "--email", "new-guest@example.com")

    assert asyncio.run(
        query(migrated_database_url, "SELECT name FROM categories ORDER BY name")
    ) == [("Capacitors",), ("Passives",), ("Resistors",)]
