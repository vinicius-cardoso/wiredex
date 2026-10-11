from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from wiredex.preferences.domain.preferences import WorkspaceId
from wiredex.preferences.infrastructure.repositories import SqlPreferences
from wiredex.shared_kernel.infrastructure.unit_of_work import SqlUnitOfWork


class SqlPreferencesUnitOfWork(SqlUnitOfWork):
    """One transaction scoped to a workspace, with its preferences bound to the session."""

    preferences: SqlPreferences

    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], workspace_id: WorkspaceId
    ) -> None:
        super().__init__(session_factory, workspace_id)
        self._scope = workspace_id

    async def __aenter__(self) -> Self:
        await super().__aenter__()
        self.preferences = SqlPreferences(self.session, self._scope)
        return self
