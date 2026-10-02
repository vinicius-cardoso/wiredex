from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from wiredex.history.domain.values import WorkspaceId
from wiredex.history.infrastructure.repositories import SqlHistoryChanges
from wiredex.shared_kernel.infrastructure.unit_of_work import SqlUnitOfWork


class SqlHistoryUnitOfWork(SqlUnitOfWork):
    """One transaction with history's repository bound to its session and workspace, which both
    of ADR 0007's gates need: every history row belongs to one."""

    changes: SqlHistoryChanges

    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], workspace_id: WorkspaceId
    ) -> None:
        super().__init__(session_factory, workspace_id)
        # Kept under its own name: the base holds a plain UUID, the repository speaks history's.
        self._workspace = workspace_id

    async def __aenter__(self) -> Self:
        await super().__aenter__()
        self.changes = SqlHistoryChanges(self.session, self._workspace)
        return self
