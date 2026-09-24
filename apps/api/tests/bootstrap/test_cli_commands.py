from typing import Any

import pytest
from alembic import command
from click.testing import CliRunner

from wiredex.bootstrap import cli as cli_module
from wiredex.bootstrap.cli import cli
from wiredex.bootstrap.migrations import AppLogin, alembic_config, next_revision_id

Calls = list[tuple[str, tuple[Any, ...], dict[str, Any]]]


@pytest.fixture
def alembic_calls(monkeypatch: pytest.MonkeyPatch) -> Calls:
    """Record the Alembic command each CLI command calls, without touching a database."""
    calls: Calls = []
    for name in ("upgrade", "downgrade", "revision", "check", "current"):

        def record(*args: Any, _name: str = name, **kwargs: Any) -> None:
            calls.append((_name, args[1:], kwargs))

        monkeypatch.setattr(command, name, record)

    async def let_app_role_log_in(admin_url: str, login: AppLogin) -> bool:
        calls.append(("let_app_role_log_in", (admin_url, login), {}))
        return True

    monkeypatch.setattr(cli_module, "let_app_role_log_in", let_app_role_log_in)
    return calls


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (["upgrade"], ("upgrade", ("head",))),
        (["upgrade", "0001"], ("upgrade", ("0001",))),
        (["downgrade", "base"], ("downgrade", ("base",))),
        (["check"], ("check", ())),
        (["current"], ("current", ())),
    ],
)
def test_commands_call_alembic(
    alembic_calls: Calls, arguments: list[str], expected: tuple[str, tuple[str, ...]]
) -> None:
    result = CliRunner().invoke(cli, ["db", *arguments])

    assert result.exit_code == 0, result.output
    name, args, _ = alembic_calls[0]
    assert (name, args) == expected


def test_revision_autogenerates_with_the_next_sequential_id(alembic_calls: Calls) -> None:
    result = CliRunner().invoke(cli, ["db", "revision", "-m", "add users"])

    assert result.exit_code == 0, result.output
    expected_id = next_revision_id(alembic_config("postgresql+asyncpg://unused@localhost/unused"))
    assert alembic_calls[0][2] == {
        "message": "add users",
        "autogenerate": True,
        "rev_id": expected_id,
    }


def test_revision_can_start_empty(alembic_calls: Calls) -> None:
    CliRunner().invoke(cli, ["db", "revision", "-m", "data fix", "--empty"])

    assert alembic_calls[0][2]["autogenerate"] is False


def test_upgrade_gives_the_app_role_the_password_from_the_api_url(alembic_calls: Calls) -> None:
    result = CliRunner().invoke(
        cli,
        ["db", "upgrade"],
        env={
            "WIREDEX_DATABASE_URL": "postgresql+asyncpg://wiredex_app:s3cret@db/wiredex",
            "WIREDEX_ADMIN_DATABASE_URL": "postgresql+asyncpg://wiredex:owner@db/wiredex",
        },
    )

    assert result.exit_code == 0, result.output
    assert alembic_calls[1] == (
        "let_app_role_log_in",
        ("postgresql+asyncpg://wiredex:owner@db/wiredex", AppLogin("s3cret")),
        {},
    )
    assert "wiredex_app can log in" in result.output


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql+asyncpg://wiredex:owner@db/wiredex",
        "postgresql+asyncpg://wiredex_app@db/wiredex",
    ],
    ids=["schema owner", "no password"],
)
def test_upgrade_refuses_an_api_url_that_is_not_the_app_role_before_migrating(
    alembic_calls: Calls, database_url: str
) -> None:
    result = CliRunner().invoke(cli, ["db", "upgrade"], env={"WIREDEX_DATABASE_URL": database_url})

    assert result.exit_code == 1
    assert "must log in as wiredex_app" in result.output
    assert alembic_calls == []
