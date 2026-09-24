from typing import Any

import pytest
from alembic import command
from click.testing import CliRunner

from wiredex.bootstrap.cli import cli

Calls = list[tuple[str, tuple[Any, ...], dict[str, Any]]]


@pytest.fixture
def alembic_calls(monkeypatch: pytest.MonkeyPatch) -> Calls:
    """Record the Alembic command each CLI command calls, without touching a database."""
    calls: Calls = []
    for name in ("upgrade", "downgrade", "revision", "check", "current"):

        def record(*args: Any, _name: str = name, **kwargs: Any) -> None:
            calls.append((_name, args[1:], kwargs))

        monkeypatch.setattr(command, name, record)
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
    assert alembic_calls[0][2] == {"message": "add users", "autogenerate": True, "rev_id": "0002"}


def test_revision_can_start_empty(alembic_calls: Calls) -> None:
    CliRunner().invoke(cli, ["db", "revision", "-m", "data fix", "--empty"])

    assert alembic_calls[0][2]["autogenerate"] is False
