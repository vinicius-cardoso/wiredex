"""History's use cases: the feed, a record's timeline, and clearing a demo bench's history.

Each opens a history transaction and closes it before it answers. A timeline first asks the
module that owns its record whether the record is live, in that module's own transaction, which
is closed before history's opens: never two at once (AGENTS.md).
"""

from collections.abc import Callable
from uuid import UUID

from wiredex.history.application.ports import HistoryUnitOfWork, Records, VersionRestorers
from wiredex.history.domain.errors import ChangeNotFoundError, RecordNotFoundError
from wiredex.history.domain.history import ActivityFilter, Change, RecordKind
from wiredex.history.domain.restore import TakeOutOfTrash, plan_restore
from wiredex.history.domain.values import ChangeId, WorkspaceId
from wiredex.shared_kernel.domain.paging import Page, PageRequest

type UnitOfWorkFactory = Callable[[WorkspaceId], HistoryUnitOfWork]


async def _paged(
    work: HistoryUnitOfWork,
    page: PageRequest,
    record: tuple[RecordKind, UUID] | None = None,
    narrowing: ActivityFilter | None = None,
) -> Page[Change]:
    """The page asked for, or the last one when it lies past the end: counted first, in the
    same transaction and over the same filters as the changes it then reads."""
    total = await work.changes.count(record, narrowing)
    served = page.within(total)
    found = await work.changes.page(served, record, narrowing)
    return Page(tuple(found), total, served)


class ListActivity:
    """A page of the workspace's changes, newest first (requirements 2.1 to 2.5), narrowed by
    the kind of record, what the change did and a fragment of the record's name when asked."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(
        self,
        workspace_id: WorkspaceId,
        page: PageRequest,
        narrowing: ActivityFilter | None = None,
    ) -> Page[Change]:
        async with self._unit_of_work(workspace_id) as work:
            return await _paged(work, page, narrowing=narrowing)


class ListTimeline:
    """A page of one record's changes, those to what it holds included (requirement 3)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory, records: Records) -> None:
        self._unit_of_work = unit_of_work
        self._records = records

    async def __call__(
        self,
        workspace_id: WorkspaceId,
        record: tuple[RecordKind, UUID],
        page: PageRequest,
    ) -> Page[Change]:
        kind, record_id = record
        if not await self._records.exists(workspace_id, kind, record_id):
            raise RecordNotFoundError(f"that {kind.value} doesn't exist")
        async with self._unit_of_work(workspace_id) as work:
            return await _paged(work, page, record=record)


class RestoreVersion:
    """A record put back as it was just before a change, through the module that owns it
    (requirement 4, decision 8).

    The change is read in a history transaction, closed before the module's own opens: the
    restore is the module's edit, under its rules, and the trigger records it as a new change,
    so the version it replaces stays in history (requirement 4.2).
    """

    def __init__(self, unit_of_work: UnitOfWorkFactory, restorers: VersionRestorers) -> None:
        self._unit_of_work = unit_of_work
        self._restorers = restorers

    async def __call__(self, workspace_id: WorkspaceId, change_id: ChangeId) -> None:
        async with self._unit_of_work(workspace_id) as work:
            found = await work.changes.own_row(change_id)
        if found is None:
            raise ChangeNotFoundError("that change doesn't exist")
        record, own_row = found
        plan = plan_restore(record, own_row)
        if isinstance(plan, TakeOutOfTrash):
            await self._restorers.take_out_of_trash(workspace_id, plan.record)
        else:
            await self._restorers.put_back(workspace_id, plan)


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
