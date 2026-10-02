"""History's tables read and cleared with Core queries, each filtered on the workspace before the
policies narrow it too (ADR 0007)."""

import typing
from typing import Any

from sqlalchemy import CursorResult, delete
from sqlalchemy.ext.asyncio import AsyncSession

from wiredex.history.domain.values import WorkspaceId
from wiredex.history.infrastructure.orm import history_changes


class SqlHistoryChanges:
    def __init__(self, session: AsyncSession, workspace_id: WorkspaceId) -> None:
        self._session = session
        self._workspace_id = workspace_id

    async def clear(self) -> int:
        # The rows go with their change: `history_entries.change_id` cascades.
        result = await self._session.execute(
            delete(history_changes).where(history_changes.c.workspace_id == self._workspace_id)
        )
        return typing.cast("CursorResult[Any]", result).rowcount
