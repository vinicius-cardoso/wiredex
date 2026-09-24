import asyncio

import pytest
from alembic import command
from click.testing import CliRunner
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import create_async_engine

from wiredex.bootstrap.cli import cli
from wiredex.bootstrap.migrations import APP_ROLE, AppLogin, alembic_config, let_app_role_log_in

pytestmark = pytest.mark.integration


def test_migrations_upgrade_downgrade_and_upgrade_again(database_url: str) -> None:
    config = alembic_config(database_url)

    command.upgrade(config, "head")
    command.downgrade(config, "base")
    command.upgrade(config, "head")


def test_models_and_migrations_agree(database_url: str) -> None:
    config = alembic_config(database_url)
    command.upgrade(config, "head")

    # Raises if autogenerate would produce operations: a model change without a migration.
    command.check(config)


def test_the_upgrade_command_lets_the_api_log_in_as_the_app_role(database_url: str) -> None:
    app_url = make_url(database_url).set(username=APP_ROLE, password="fresh:password'%")
    app_url_text = app_url.render_as_string(hide_password=False)

    result = CliRunner().invoke(
        cli,
        ["db", "upgrade"],
        env={"WIREDEX_ADMIN_DATABASE_URL": database_url, "WIREDEX_DATABASE_URL": app_url_text},
    )

    assert result.exit_code == 0, result.output
    assert asyncio.run(_current_user(app_url_text)) == APP_ROLE


def test_the_app_login_waits_for_the_migration_that_creates_the_role(database_url: str) -> None:
    config = alembic_config(database_url)
    command.downgrade(config, "0003")
    try:
        granted = asyncio.run(let_app_role_log_in(database_url, AppLogin("unused")))
    finally:
        command.upgrade(config, "head")

    assert granted is False


async def _current_user(database_url: str) -> str | None:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            user: str | None = await connection.scalar(text("SELECT current_user"))
            return user
    finally:
        await engine.dispose()
