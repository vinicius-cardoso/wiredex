"""Watching what SQLAlchemy actually sends, for the promises code makes about cost.

A read that says it costs one query and a save that says it costs two statements look exactly
like ones that don't: the rows come back either way. Counting the statements is what holds
them to it (requirements 7.1 and 7.2), so the counter lives here, for any repository test.
Counting commits, and every table's rows, does the same for a use case that promises one
transaction, or none.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Connection, event, text
from sqlalchemy.ext.asyncio import AsyncEngine


@contextmanager
def committing(engine: AsyncEngine) -> Iterator[list[None]]:
    """One entry per transaction a block commits, so a write that promised one is held to it.

    A savepoint's release isn't a commit, so a repository's nested insert doesn't count.
    """

    def record(_connection: Connection) -> None:
        commits.append(None)

    commits: list[None] = []
    event.listen(engine.sync_engine, "commit", record)
    try:
        yield commits
    finally:
        event.remove(engine.sync_engine, "commit", record)


@contextmanager
def counting(engine: AsyncEngine) -> Iterator[list[str]]:
    """The statements a block runs, so a query that promised one round trip is held to it."""

    def record(_connection: Connection, _cursor: Any, statement: str, *_rest: Any) -> None:
        statements.append(statement)

    statements: list[str] = []
    event.listen(engine.sync_engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record)


async def row_counts(owner: AsyncEngine) -> dict[str, int]:
    """How many rows every table holds, the migrations' own bookkeeping included.

    Read by the schema owner, whom row-level security doesn't narrow, so a row written into
    any workspace counts. A table added later is counted without this changing.
    """
    async with owner.connect() as connection:
        tables = await connection.scalars(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY 1")
        )
        counts: dict[str, int] = {}
        for table in tables.all():
            # The names come from the catalog itself, never from input.
            total = await connection.scalar(text(f'SELECT count(*) FROM "{table}"'))  # noqa: S608
            counts[str(table)] = int(total or 0)
        return counts
