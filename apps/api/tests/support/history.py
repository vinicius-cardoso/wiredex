"""History's ports in memory: the changes a test holds, per workspace, the units of work opened
over them, and the modules' answers about which records are live."""

from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Self
from uuid import UUID, uuid4, uuid7

from wiredex.history.domain.history import (
    Change,
    Operation,
    RecordKind,
    RecordRef,
    RowChange,
    RowKind,
)
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
    row = RowChange(
        RowKind.PART,
        Operation.UPDATE,
        True,
        ("name",),
        before or {"name": "R"},
        after or {"name": "R 4k7"},
    )
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
