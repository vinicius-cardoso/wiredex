import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from wiredex.system.infrastructure.sql_database_probe import SqlDatabaseProbe

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


async def test_probe_reaches_a_real_postgres(database_url: str) -> None:
    engine = create_async_engine(database_url)
    try:
        assert await SqlDatabaseProbe(engine).is_reachable() is True
    finally:
        await engine.dispose()
