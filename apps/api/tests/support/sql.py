"""Watching what SQLAlchemy actually sends, for the promises a repository makes about cost.

A read that says it costs one query and a save that says it costs two statements look exactly
like ones that don't: the rows come back either way. Counting the statements is what holds
them to it (requirements 7.1 and 7.2), so the counter lives here, for any repository test.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Connection, event
from sqlalchemy.ext.asyncio import AsyncEngine


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
