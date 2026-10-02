"""History's ports in memory: the changes a test holds, per workspace, the units of work opened
over them, and the modules' answers about which records are live."""

from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Self
from uuid import UUID, uuid4, uuid7

from wiredex.history.domain.errors import NotRestorableError, RecordNotFoundError
from wiredex.history.domain.history import (
    Change,
    Operation,
    RecordKind,
    RecordRef,
    RowChange,
    RowKind,
)
from wiredex.history.domain.restore import PutBack
from wiredex.history.domain.values import ChangeId, WorkspaceId

BENCH = WorkspaceId(uuid7())
START = datetime(2026, 10, 1, 9, tzinfo=UTC)


def a_part_edit(
    number: int,
    record: RecordRef | None = None,
    before: dict[str, object] | None = None,
    after: dict[str, object] | None = None,
) -> Change:
    """Change NUMBER, renaming a part: `R` became `R 4k7` unless told otherwise."""
    record = record or RecordRef(RecordKind.PART, uuid4(), "R 4k7")
    before = before or {"name": "R"}
    after = after or {"name": "R 4k7"}
    # As the trigger lists them: what differs, compared whole.
    changed = tuple(sorted(name for name in after if before.get(name) != after.get(name)))
    row = RowChange(RowKind.PART, Operation.UPDATE, True, changed, before, after)
    return Change(
        ChangeId(number), START + timedelta(minutes=number), "Owner", None, record, (row,), 1
    )


class InMemoryHistoryChanges:
    def __init__(self) -> None:
        self.saved: dict[WorkspaceId, list[Change]] = {}
        self.workspace_id = BENCH
        self.asked: list[tuple[ChangeId | None, int, tuple[RecordKind, UUID] | None]] = []

    def hold(self, *changes: Change, workspace_id: WorkspaceId = BENCH) -> None:
        self.saved.setdefault(workspace_id, []).extend(changes)

    async def page(
        self,
        before: ChangeId | None,
        limit: int,
        record: tuple[RecordKind, UUID] | None = None,
    ) -> list[Change]:
        self.asked.append((before, limit, record))
        held = sorted(self.saved.get(self.workspace_id, []), key=lambda c: c.id, reverse=True)
        found = [
            change
            for change in held
            if (before is None or change.id < before)
            and (record is None or (change.record.kind, change.record.id) == record)
        ]
        return found[:limit]

    async def own_row(self, change_id: ChangeId) -> tuple[RecordRef, RowChange | None] | None:
        for change in self.saved.get(self.workspace_id, []):
            if change.id == change_id:
                return change.record, change.own_row
        return None

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


class FakeRecords:
    """The modules' answer to whether a record is live: the ones a test names."""

    def __init__(self) -> None:
        self.live: set[tuple[WorkspaceId, RecordKind, UUID]] = set()
        self.asked: list[tuple[RecordKind, UUID]] = []

    def add(self, record: RecordRef, workspace_id: WorkspaceId = BENCH) -> None:
        self.live.add((workspace_id, record.kind, record.id))

    async def exists(self, workspace_id: WorkspaceId, kind: RecordKind, record_id: UUID) -> bool:
        self.asked.append((kind, record_id))
        return (workspace_id, kind, record_id) in self.live


class FakeRestorers:
    """The modules' restores, logged; `refuse` is the sentence a module refuses with, and
    `gone` the records a module no longer holds."""

    def __init__(self) -> None:
        self.put_back_plans: list[tuple[WorkspaceId, PutBack]] = []
        self.out_of_trash: list[tuple[WorkspaceId, RecordRef]] = []
        self.refuse: str | None = None
        self.gone: set[UUID] = set()

    async def put_back(self, workspace_id: WorkspaceId, plan: PutBack) -> None:
        self._check(plan.record)
        self.put_back_plans.append((workspace_id, plan))

    async def take_out_of_trash(self, workspace_id: WorkspaceId, record: RecordRef) -> None:
        self._check(record)
        self.out_of_trash.append((workspace_id, record))

    def _check(self, record: RecordRef) -> None:
        if record.id in self.gone:
            raise RecordNotFoundError(f"that {record.kind.value} doesn't exist")
        if self.refuse is not None:
            raise NotRestorableError(self.refuse)
