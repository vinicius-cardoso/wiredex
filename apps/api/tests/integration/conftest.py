from collections.abc import Iterator

import pytest
from alembic import command
from testcontainers.community.postgres import PostgresContainer

from wiredex.bootstrap.migrations import alembic_config

# Same major and minor as compose.yaml and production.
POSTGRES_IMAGE = "postgres:18.6-alpine"


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
