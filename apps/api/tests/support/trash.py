"""In-memory bins for the trash's use cases and routes: one kind each, as `bootstrap/trash.py`
builds them over the modules.

A bin holds its kind's records in the trash, answers a page the way the repositories do (newest
first, before a position, at most `limit`), and logs every call, so a test can check that the
trash asked one bin at a time and the right bin for a write.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid7

import anyio

from wiredex.shared_kernel.domain.trash import TrashPosition
from wiredex.trash.application.trash import (
    DeleteFromTrash,
    EmptyTrash,
    ListTrash,
    RestoreFromTrash,
)
from wiredex.trash.domain.errors import TrashItemNotFoundError
from wiredex.trash.domain.trash import TrashedItem, TrashKind
from wiredex.trash.domain.values import WorkspaceId

BENCH = WorkspaceId(uuid7())
START = datetime(2026, 10, 1, 9, tzinfo=UTC)


def an_item(
    kind: TrashKind, minutes: int, name: str = "", detail: str | None = None
) -> TrashedItem:
    """A record of the kind moved to the trash `minutes` after START."""
    return TrashedItem(
        kind=kind,
        id=uuid7(),
        name=name or f"{kind.value} {minutes}",
        detail=detail,
        trashed_at=START + timedelta(minutes=minutes),
    )


@dataclass
class FakeBin:
    """One kind's bin. `log` is shared between the bins of one trash, so it records the order
    in which they were asked, and `open` whether two were asked at once."""

    trash_kind: TrashKind
    log: list[str]
    held: list[TrashedItem] = field(default_factory=list)
    asked: list[tuple[TrashPosition | None, int]] = field(default_factory=list)
    open: list[TrashKind] = field(default_factory=list)
    overlapped: bool = False

    @property
    def kind(self) -> TrashKind:
        return self.trash_kind

    async def page(
        self, workspace_id: WorkspaceId, before: TrashPosition | None, limit: int
    ) -> Sequence[TrashedItem]:
        async with self._call("page", workspace_id):
            self.asked.append((before, limit))
            newest = sorted(self.held, key=lambda item: item.position, reverse=True)
            return [item for item in newest if before is None or item.position < before][:limit]

    async def restore(self, workspace_id: WorkspaceId, item_id: UUID) -> None:
        async with self._call("restore", workspace_id):
            self._take(item_id)

    async def delete(self, workspace_id: WorkspaceId, item_id: UUID) -> None:
        async with self._call("delete", workspace_id):
            self._take(item_id)

    async def empty(self, workspace_id: WorkspaceId) -> None:
        async with self._call("empty", workspace_id):
            self.held.clear()

    def _take(self, item_id: UUID) -> None:
        for item in self.held:
            if item.id == item_id:
                self.held.remove(item)
                return
        raise TrashItemNotFoundError(f"that {self.trash_kind.value} isn't in the trash")

    def _call(self, what: str, workspace_id: WorkspaceId) -> _Call:
        assert workspace_id == BENCH
        return _Call(self, what)


class _Call:
    """One call into a bin: logged, and yielding once in the middle, so two calls the trash ran
    at once would interleave and be caught."""

    def __init__(self, trash_bin: FakeBin, what: str) -> None:
        self._bin = trash_bin
        self._what = what

    async def __aenter__(self) -> None:
        self._bin.log.append(f"{self._what} {self._bin.trash_kind.value}")
        if self._bin.open:
            self._bin.overlapped = True
        self._bin.open.append(self._bin.trash_kind)
        await anyio.sleep(0)

    async def __aexit__(self, *_exception: object) -> None:
        self._bin.open.pop()


class Trash:
    """A bin per kind over one shared log and one shared list of open calls, and the trash's
    four use cases over them."""

    def __init__(self, kinds: Iterable[TrashKind] = tuple(TrashKind)) -> None:
        self.log: list[str] = []
        shared_open: list[TrashKind] = []
        self.bins = {kind: FakeBin(kind, self.log, open=shared_open) for kind in kinds}
        bins = list(self.bins.values())
        self.list_trash = ListTrash(bins)
        self.restore = RestoreFromTrash(bins)
        self.delete = DeleteFromTrash(bins)
        self.empty = EmptyTrash(bins)

    def hold(self, *items: TrashedItem) -> None:
        for item in items:
            self.bins[item.kind].held.append(item)

    @property
    def overlapped(self) -> bool:
        return any(trash_bin.overlapped for trash_bin in self.bins.values())

    def held(self) -> list[TrashedItem]:
        return [item for trash_bin in self.bins.values() for item in trash_bin.held]
