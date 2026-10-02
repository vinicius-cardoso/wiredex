"""History's use cases: reading the changes the database recorded, and clearing a demo bench's."""

from collections.abc import Callable

from wiredex.history.application.ports import HistoryUnitOfWork
from wiredex.history.domain.values import WorkspaceId

type UnitOfWorkFactory = Callable[[WorkspaceId], HistoryUnitOfWork]


class ClearHistory:
    """Every change of a workspace deleted, for a demo bench just seeded or reset: its history
    starts empty, as its samples start fresh (17-history, requirement 5.4)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId) -> int:
        async with self._unit_of_work(workspace_id) as work:
            cleared = await work.changes.clear()
            await work.commit()
            return cleared
