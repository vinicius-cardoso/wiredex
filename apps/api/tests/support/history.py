"""History's ports in memory: the changes a test holds, per workspace, and the units of work
opened over them."""

from types import TracebackType
from typing import Self
from uuid import uuid7

from wiredex.history.domain.history import Change
from wiredex.history.domain.values import WorkspaceId

BENCH = WorkspaceId(uuid7())


class InMemoryHistoryChanges:
    def __init__(self) -> None:
        self.saved: dict[WorkspaceId, list[Change]] = {}
        self.workspace_id = BENCH

    async def clear(self) -> int:
        cleared = len(self.saved.get(self.workspace_id, []))
        self.saved[self.workspace_id] = []
        return cleared


class InMemoryHistoryUnitOfWork:
    """One fake unit of work, reopened for each workspace a use case names."""

    def __init__(self) -> None:
        self.changes = InMemoryHistoryChanges()
        self.opened_for: list[WorkspaceId] = []
        self.commits = 0

    def for_workspace(self, workspace_id: WorkspaceId) -> InMemoryHistoryUnitOfWork:
        self.opened_for.append(workspace_id)
        self.changes.workspace_id = workspace_id
        return self

    async def commit(self) -> None:
        self.commits += 1

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None
