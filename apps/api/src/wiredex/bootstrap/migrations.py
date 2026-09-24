from dataclasses import dataclass
from typing import Self

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import create_async_engine

SCRIPT_LOCATION = "wiredex:migrations"
APP_ROLE = "wiredex_app"  # created by migration 0004


class AppLoginError(ValueError):
    """The API's database URL doesn't log in as the app role."""


def alembic_config(database_url: str) -> Config:
    """Alembic settings built in code: there is no alembic.ini to keep in sync."""
    config = Config()
    config.set_main_option("script_location", SCRIPT_LOCATION)
    # File names follow the revision id: 0001_baseline.py, 0002_identity.py, ...
    config.set_main_option("file_template", "%%(rev)s_%%(slug)s")
    # Generated migrations go through ruff, so they pass `make lint` as written.
    config.set_section_option("post_write_hooks", "hooks", "ruff_fix, ruff_format")
    config.set_section_option("post_write_hooks", "ruff_fix.type", "module")
    config.set_section_option("post_write_hooks", "ruff_fix.module", "ruff")
    config.set_section_option(
        "post_write_hooks", "ruff_fix.options", "check --fix --quiet REVISION_SCRIPT_FILENAME"
    )
    config.set_section_option("post_write_hooks", "ruff_format.type", "module")
    config.set_section_option("post_write_hooks", "ruff_format.module", "ruff")
    config.set_section_option(
        "post_write_hooks", "ruff_format.options", "format --quiet REVISION_SCRIPT_FILENAME"
    )
    config.attributes["database_url"] = database_url
    return config


def next_revision_id(config: Config) -> str:
    """Sequential, readable revision ids (0001, 0002, ...) instead of random hashes."""
    heads = ScriptDirectory.from_config(config).get_heads()
    return f"{max((int(head) for head in heads), default=0) + 1:04d}"


@dataclass(frozen=True, slots=True)
class AppLogin:
    """The app role's password, taken from the API's database URL."""

    password: str

    @classmethod
    def from_url(cls, database_url: str) -> Self:
        url = make_url(database_url)
        if url.username != APP_ROLE or not url.password:
            raise AppLoginError(
                f"WIREDEX_DATABASE_URL must log in as {APP_ROLE}, with a password. "
                "The schema owner belongs in WIREDEX_ADMIN_DATABASE_URL."
            )
        return cls(str(url.password))


async def let_app_role_log_in(admin_url: str, login: AppLogin) -> bool:
    """Give the app role its login. False when no migration has created the role yet.

    Setting it on every upgrade keeps the database in step with the password in the
    API's configuration, which is the only place it's kept.
    """
    engine = create_async_engine(admin_url)
    try:
        async with engine.begin() as connection:
            # ALTER ROLE takes no parameters: Postgres quotes the password itself.
            statement = await connection.scalar(
                text(
                    "SELECT format('ALTER ROLE %I LOGIN PASSWORD %L',"
                    " rolname, CAST(:password AS text))"
                    " FROM pg_roles WHERE rolname = :role"
                ),
                {"role": APP_ROLE, "password": login.password},
            )
            if statement is None:
                return False
            await connection.exec_driver_sql(statement)
    finally:
        await engine.dispose()
    return True
