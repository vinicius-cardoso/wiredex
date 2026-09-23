import asyncio

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine


class SqlDatabaseProbe:
    """DatabaseProbe that runs `SELECT 1`, giving up after a short timeout."""

    def __init__(self, engine: AsyncEngine, timeout_seconds: float = 2.0) -> None:
        self._engine = engine
        self._timeout_seconds = timeout_seconds

    async def is_reachable(self) -> bool:
        try:
            async with asyncio.timeout(self._timeout_seconds):
                async with self._engine.connect() as connection:
                    await connection.execute(text("SELECT 1"))
        except SQLAlchemyError, OSError, TimeoutError:
            return False
        return True
