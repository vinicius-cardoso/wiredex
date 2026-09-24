from uuid import uuid7

import pytest
from click.testing import CliRunner

from wiredex.bootstrap import cli as cli_module
from wiredex.identity.application.create_account import CreatedAccount, NewAccount
from wiredex.identity.domain.values import UserId, WorkspaceId


def test_the_password_is_prompted_twice_and_hidden(monkeypatch: pytest.MonkeyPatch) -> None:
    received: list[NewAccount] = []

    async def fake_create(account: NewAccount) -> CreatedAccount:
        received.append(account)
        return CreatedAccount(UserId(uuid7()), WorkspaceId(uuid7()))

    monkeypatch.setattr(cli_module, "_create_account", fake_create)
    password = "correct horse battery"

    result = CliRunner().invoke(
        cli_module.cli,
        ["users", "create", "--email", "me@example.com", "--name", "Me"],
        input=f"{password}\n{password}\n",
    )

    assert result.exit_code == 0, result.output
    assert result.output.count("Password") == 1
    assert "Repeat for confirmation" in result.output
    assert password not in result.output  # hidden input is never echoed
    assert received[0].password.value == password
