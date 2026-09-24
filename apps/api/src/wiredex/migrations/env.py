"""Alembic environment: runs migrations over an async engine.

The URL comes from `config.attributes`, not the ini options, so a password with a `%`
never hits ConfigParser interpolation. See wiredex.bootstrap.migrations.
"""

import asyncio
from typing import Literal

from alembic import context
from alembic.autogenerate.api import AutogenContext
from sqlalchemy import TypeDecorator
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from wiredex.bootstrap import orm  # noqa: F401  registers every module's tables
from wiredex.shared_kernel.infrastructure.orm import metadata


def render_item(kind: str, item: object, _context: AutogenContext) -> str | Literal[False]:
    """Write app column types (EmailType, ...) as their plain database type.

    A migration must not import application code: it has to keep working after the
    code it was generated from changes or disappears.
    """
    if kind == "type" and isinstance(item, TypeDecorator):
        return f"sa.{item.impl!r}"
    return False


def run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=metadata,
        compare_type=True,
        render_item=render_item,
    )
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
