from click.testing import CliRunner

from wiredex.bootstrap.cli import cli
from wiredex.bootstrap.migrations import alembic_config, next_revision_id


def test_db_group_lists_the_migration_commands() -> None:
    result = CliRunner().invoke(cli, ["db", "--help"])

    assert result.exit_code == 0
    for command in ("upgrade", "downgrade", "revision", "check", "current"):
        assert command in result.output


def test_revision_ids_count_up_from_the_newest_migration() -> None:
    # Reading the script directory needs no database.
    config = alembic_config("postgresql+asyncpg://unused@localhost/unused")

    assert next_revision_id(config) == "0002"
