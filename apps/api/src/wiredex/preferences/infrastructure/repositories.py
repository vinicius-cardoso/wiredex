from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from wiredex.preferences.domain.preferences import WorkspaceId, WorkspacePreferences
from wiredex.preferences.infrastructure.orm import workspace_preferences


class SqlPreferences:
    def __init__(self, session: AsyncSession, workspace_id: WorkspaceId) -> None:
        self._session = session
        self._workspace_id = workspace_id

    async def get(self) -> WorkspacePreferences | None:
        # Filtered here as well as by row-level security, ADR 0007's two gates.
        found = await self._session.execute(
            select(WorkspacePreferences).where(
                workspace_preferences.c.workspace_id == self._workspace_id
            )
        )
        return found.scalar_one_or_none()

    async def add(self, preferences: WorkspacePreferences) -> None:
        self._session.add(preferences)
