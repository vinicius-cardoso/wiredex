"""Alembic environment: runs migrations over an async engine.

The URL comes from `config.attributes`, not the ini options, so a password with a `%`
never hits ConfigParser interpolation. See wiredex.bootstrap.migrations.
"""

import asyncio

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from wiredex.bootstrap import orm  # noqa: F401  registers every module's tables
from wiredex.shared_kernel.infrastructure.orm import metadata


def run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_online() -> None:
    engine = create_async_engine(context.config.attributes["database_url"])
    async with engine.connect() as connection:
        await connection.run_sync(run_migrations)
    await engine.dispose()


if context.is_offline_mode():  # pragma: no cover  (never used; refused on purpose)
    raise SystemExit("Offline (SQL script) migrations are not supported; run them online.")
asyncio.run(run_online())
