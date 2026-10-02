"""Wire the history module: its unit of work over Postgres, and its use cases.

The database records every change through `record_history()` (17-history, decision 1); this file
is what reads them back, and what clears a demo bench's once its samples are back.
"""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.settings import Settings
from wiredex.history.application.history import ClearHistory
from wiredex.history.domain.values import WorkspaceId
from wiredex.history.infrastructure.unit_of_work import SqlHistoryUnitOfWork

type SessionFactory = async_sessionmaker[AsyncSession]


def _history_unit_of_work(
    session_factory: SessionFactory,
) -> Callable[[WorkspaceId], SqlHistoryUnitOfWork]:
    # One unit of work per workspace, as every module's is: the id reaches both of ADR 0007's
    # gates, the repository's filter and the policies.
    return lambda workspace_id: SqlHistoryUnitOfWork(session_factory, workspace_id)


@asynccontextmanager
async def clear_history_use_case(settings: Settings) -> AsyncIterator[ClearHistory]:
    """ClearHistory over Postgres, for the benches a demo invite or reset has just seeded: a
    bench's history starts empty with its samples (requirement 5.4)."""
    engine = create_engine(settings)
    try:
        yield ClearHistory(_history_unit_of_work(create_session_factory(engine)))
    finally:
        await engine.dispose()
