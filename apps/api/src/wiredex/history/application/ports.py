"""What history's use cases need: its own tables, and through bootstrap, the modules that own the
records it is about."""

from types import TracebackType
from typing import Protocol, Self
from uuid import UUID

from wiredex.history.domain.history import (
    ActivityFilter,
    Change,
    RecordKind,
    RecordRef,
    RowChange,
)
from wiredex.history.domain.restore import PutBack
from wiredex.history.domain.values import ChangeId, WorkspaceId
from wiredex.shared_kernel.domain.paging import PageRequest


class HistoryChanges(Protocol):
    """The workspace's changes, as the database recorded them."""

    async def count(
        self,
        record: tuple[RecordKind, UUID] | None = None,
        narrowing: ActivityFilter | None = None,
    ) -> int:
        """How many changes `page` pages through with the same `record` and `narrowing`, in one
        statement."""
        ...

    async def page(
        self,
        page: PageRequest,
        record: tuple[RecordKind, UUID] | None = None,
        narrowing: ActivityFilter | None = None,
    ) -> list[Change]:
        """The changes of that page, newest first by their unique id, so the pages never overlap,
        each with its first rows; only one record's when `record` names it, and only those
        `narrowing` matches when it is given. In a fixed number of statements (8.3)."""
        ...

    async def own_row(self, change_id: ChangeId) -> tuple[RecordRef, RowChange | None] | None:
        """The change's record and its first row of the record itself, with its whole
        snapshots; None for a change the workspace doesn't hold."""
        ...

    async def clear(self) -> int:
        """Every change of the workspace deleted, their rows with them; how many went."""
        ...


class HistoryUnitOfWork(Protocol):
    @property
    def changes(self) -> HistoryChanges: ...

    async def commit(self) -> None: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...


class Records(Protocol):
    """Whether a part, unit, project or firmware is live in the workspace, asked of the module
    that owns it: what a timeline's 404 follows, so it answers as the record's page does."""

    async def exists(
        self, workspace_id: WorkspaceId, kind: RecordKind, record_id: UUID
    ) -> bool: ...


class VersionRestorers(Protocol):
    """A restore carried out by the module that owns the record, in its own transaction and
    under the reason `restore`, so its rules apply and the trigger records a new change.

    Each raises `NotRestorableError` with the module's sentence for what it refuses, and
    `RecordNotFoundError` for a record it no longer holds (requirements 4.3, 4.4).
    """

    async def put_back(self, workspace_id: WorkspaceId, plan: PutBack) -> None: ...

    async def take_out_of_trash(self, workspace_id: WorkspaceId, record: RecordRef) -> None: ...
