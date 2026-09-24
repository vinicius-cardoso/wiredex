import asyncio

import pytest
from click.testing import CliRunner
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from wiredex.bootstrap.cli import cli

pytestmark = pytest.mark.integration


def create_user(database_url: str, email: str, password: str) -> tuple[int, str]:
    result = CliRunner().invoke(
        cli,
        ["users", "create", "--email", email, "--name", "Vinícius", "--password-stdin"],
        input=f"{password}\n",
        env={"WIREDEX_DATABASE_URL": database_url},
    )
    return result.exit_code, result.output


def test_users_create_makes_an_owner_with_a_personal_workspace(
    migrated_database_url: str,
) -> None:
    exit_code, output = create_user(
        migrated_database_url, "Owner@Example.com", "correct horse battery"
    )

    assert exit_code == 0, output
    assert "Created owner@example.com, owner of workspace" in output
    assert asyncio.run(_accounts(migrated_database_url)) == [
        ("owner@example.com", "Vinícius", "personal", "owner", True)
    ]


def test_users_create_refuses_a_taken_email(migrated_database_url: str) -> None:
    create_user(migrated_database_url, "taken@example.com", "correct horse battery")

    exit_code, output = create_user(
        migrated_database_url, "TAKEN@example.com", "another long password"
    )

    assert exit_code == 1
    assert "taken@example.com already has an account" in output


def test_users_create_refuses_a_short_password(migrated_database_url: str) -> None:
    exit_code, output = create_user(migrated_database_url, "short@example.com", "tooshort")

    assert exit_code == 1
    assert "between 12 and 1024 characters" in output


async def _accounts(database_url: str) -> list[tuple[object, ...]]:
    """Each account with its workspace kind, role, and whether the hash is Argon2id."""
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text(
                    "SELECT u.email, u.name, w.kind, m.role,"
                    " u.password_hash LIKE '$argon2id$%'"
                    " FROM users u JOIN memberships m ON m.user_id = u.id"
                    " JOIN workspaces w ON w.id = m.workspace_id ORDER BY u.email"
                )
            )
            return [tuple(row) for row in result]
    finally:
        await engine.dispose()
