"""The trash's use cases: one list across the bins, and each write handed to its kind's bin.

The bins are asked one after the other, never at once: each opens its module's unit of work and
closes it before the next one opens, so a request holds one pooled connection at a time
(decision 8).
"""

from collections.abc import Mapping, Sequence
from uuid import UUID

from wiredex.trash.application.ports import TrashBin
from wiredex.trash.domain.errors import TrashItemNotFoundError
from wiredex.trash.domain.trash import TrashCursor, TrashKind, TrashPage, merge
from wiredex.trash.domain.values import WorkspaceId


class ListTrash:
    """One page of the trash, newest first across every kind (requirements 4.1 to 4.3, 4.5).

    Each bin is asked for one more record than the page holds, before the same position, so the
    merge can tell whether anything is left for a next page (decision 9).
    """

    def __init__(self, bins: Sequence[TrashBin]) -> None:
        self._bins = tuple(bins)

    async def __call__(
        self, workspace_id: WorkspaceId, cursor: TrashCursor | None, limit: int
    ) -> TrashPage:
        before = None if cursor is None else cursor.position
        pages = [await trash_bin.page(workspace_id, before, limit + 1) for trash_bin in self._bins]
        return merge(pages, limit)


class RestoreFromTrash:
    """A record of a kind back from the trash, through the bin of its kind (requirement 5)."""

    def __init__(self, bins: Sequence[TrashBin]) -> None:
        self._bins = _by_kind(bins)

    async def __call__(self, workspace_id: WorkspaceId, kind: TrashKind, item_id: UUID) -> None:
        await _bin_of(self._bins, kind).restore(workspace_id, item_id)


class DeleteFromTrash:
    """A record of a kind deleted for good, through the bin of its kind (requirement 6)."""

    def __init__(self, bins: Sequence[TrashBin]) -> None:
        self._bins = _by_kind(bins)

    async def __call__(self, workspace_id: WorkspaceId, kind: TrashKind, item_id: UUID) -> None:
        await _bin_of(self._bins, kind).delete(workspace_id, item_id)


class EmptyTrash:
    """Every record in the trash deleted for good, one bin after the other (requirement 6.4,
    requirements decision 12). A bin that fails leaves the bins before it emptied: each is its
    module's own transaction, and emptying again finishes the job."""

    def __init__(self, bins: Sequence[TrashBin]) -> None:
        self._bins = tuple(bins)

    async def __call__(self, workspace_id: WorkspaceId) -> None:
        for trash_bin in self._bins:
            await trash_bin.empty(workspace_id)


def _by_kind(bins: Sequence[TrashBin]) -> Mapping[TrashKind, TrashBin]:
    return {trash_bin.kind: trash_bin for trash_bin in bins}


def _bin_of(bins: Mapping[TrashKind, TrashBin], kind: TrashKind) -> TrashBin:
    found = bins.get(kind)
    if found is None:
        raise TrashItemNotFoundError("nothing of that kind is in the trash")
    return found
