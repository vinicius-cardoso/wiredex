from collections.abc import Iterator

import pytest
from testcontainers.postgres import PostgresContainer

# Same major and minor as compose.yaml and production.
POSTGRES_IMAGE = "postgres:18.6-alpine"


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    """A throwaway Postgres for the whole test session, removed afterwards."""
    with PostgresContainer(POSTGRES_IMAGE, driver="asyncpg") as postgres:
        yield postgres.get_connection_url()
