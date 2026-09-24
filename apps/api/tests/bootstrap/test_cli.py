from pathlib import Path

from click.testing import CliRunner

from wiredex.bootstrap.cli import cli
from wiredex.bootstrap.migrations import alembic_config, next_revision_id


def test_db_group_lists_the_migration_commands() -> None:
    result = CliRunner().invoke(cli, ["db", "--help"])

    assert result.exit_code == 0
    for command in ("upgrade", "downgrade", "revision", "check", "current"):
        assert command in result.output


def write_revision(folder: Path, revision: str, down_revision: str | None) -> None:
    (folder / f"{revision}_step.py").write_text(
        f"revision = {revision!r}\ndown_revision = {down_revision!r}\n"
        "branch_labels = None\ndepends_on = None\n"
    )


def test_revision_ids_count_up_from_the_newest_migration(tmp_path: Path) -> None:
    (tmp_path / "versions").mkdir()
    write_revision(tmp_path / "versions", "0001", None)
    write_revision(tmp_path / "versions", "0007", "0001")
    config = alembic_config("postgresql+asyncpg://unused@localhost/unused")
    config.set_main_option("script_location", str(tmp_path))

    assert next_revision_id(config) == "0008"
