import asyncio
from collections.abc import Iterator

import pytest
from alembic import command
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.community.postgres import PostgresContainer

from wiredex.bootstrap.migrations import alembic_config

# Same major and minor as compose.yaml and production.
POSTGRES_IMAGE = "postgres:18.6-alpine"
APP_ROLE = "wiredex_app"
APP_PASSWORD = "app-role-password"


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    """A throwaway Postgres for the whole test session, removed afterwards."""
    with PostgresContainer(POSTGRES_IMAGE, driver="asyncpg") as postgres:
        yield postgres.get_connection_url()


@pytest.fixture
def migrated_database_url(database_url: str) -> str:
    """The same database, upgraded to the newest migration.

    Synchronous on purpose: migrations/env.py runs its own event loop, which can't
    start inside an async test's loop.
    """
    command.upgrade(alembic_config(database_url), "head")
    return database_url


@pytest.fixture
def app_database_url(migrated_database_url: str) -> str:
    """The migrated database, as the restricted role the API logs in with."""
    asyncio.run(_let_app_role_log_in(migrated_database_url))
    app_url = make_url(migrated_database_url).set(username=APP_ROLE, password=APP_PASSWORD)
    return app_url.render_as_string(hide_password=False)


async def _let_app_role_log_in(admin_url: str) -> None:
    engine = create_async_engine(admin_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f"ALTER ROLE {APP_ROLE} LOGIN PASSWORD '{APP_PASSWORD}'"))
    finally:
        await engine.dispose()
