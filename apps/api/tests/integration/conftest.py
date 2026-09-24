import asyncio
from collections.abc import Iterator

import pytest
from alembic import command
from sqlalchemy import make_url
from testcontainers.community.postgres import PostgresContainer

from wiredex.bootstrap.migrations import APP_ROLE, AppLogin, alembic_config, let_app_role_log_in

# Same major and minor as compose.yaml and production.
POSTGRES_IMAGE = "postgres:18.6-alpine"
# Quotes, colons and percent signs: the password must survive SQL and URL quoting.
APP_PASSWORD = "it's:100%-app"


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
    asyncio.run(let_app_role_log_in(migrated_database_url, AppLogin(APP_PASSWORD)))
    app_url = make_url(migrated_database_url).set(username=APP_ROLE, password=APP_PASSWORD)
    return app_url.render_as_string(hide_password=False)
