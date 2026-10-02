"""History's use cases: the feed, a record's timeline, and clearing a demo bench's history.

Each opens a history transaction and closes it before it answers. A timeline first asks the
module that owns its record whether the record is live, in that module's own transaction, which
is closed before history's opens: never two at once (AGENTS.md).
"""

from collections.abc import Callable
from uuid import UUID

from wiredex.history.application.ports import HistoryUnitOfWork, Records
from wiredex.history.domain.errors import RecordNotFoundError
from wiredex.history.domain.history import ChangeCursor, HistoryPage, RecordKind
from wiredex.history.domain.values import WorkspaceId

type UnitOfWorkFactory = Callable[[WorkspaceId], HistoryUnitOfWork]


class ListActivity:
    """A page of the workspace's changes, newest first (requirements 2.1 to 2.5)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(
        self, workspace_id: WorkspaceId, cursor: ChangeCursor | None, limit: int
    ) -> HistoryPage:
        before = None if cursor is None else cursor.change_id
        async with self._unit_of_work(workspace_id) as work:
            found = await work.changes.page(before, limit + 1)
        return HistoryPage.of(found, limit)


class ListTimeline:
    """A page of one record's changes, those to what it holds included (requirement 3)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory, records: Records) -> None:
        self._unit_of_work = unit_of_work
        self._records = records

    async def __call__(
        self,
        workspace_id: WorkspaceId,
        record: tuple[RecordKind, UUID],
        cursor: ChangeCursor | None,
        limit: int,
    ) -> HistoryPage:
        kind, record_id = record
        if not await self._records.exists(workspace_id, kind, record_id):
            raise RecordNotFoundError(f"that {kind.value} doesn't exist")
        before = None if cursor is None else cursor.change_id
        async with self._unit_of_work(workspace_id) as work:
            found = await work.changes.page(before, limit + 1, record)
        return HistoryPage.of(found, limit)


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
