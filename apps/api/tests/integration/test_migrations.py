import pytest
from alembic import command

from wiredex.bootstrap.migrations import alembic_config

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
