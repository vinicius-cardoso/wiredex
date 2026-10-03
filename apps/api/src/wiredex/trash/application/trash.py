"""The trash's use cases: one list across the bins, and each write handed to its kind's bin.

The bins are asked one after the other, never at once: each opens its module's unit of work and
closes it before the next one opens, so a request holds one pooled connection at a time
(decision 8).
"""

from collections.abc import Mapping, Sequence
from uuid import UUID

from wiredex.shared_kernel.domain.trash import TrashPosition
from wiredex.trash.application.ports import TrashBin
from wiredex.trash.domain.errors import TrashItemNotFoundError
from wiredex.trash.domain.trash import (
    MAX_PAGE_SIZE,
    TrashCursor,
    TrashedItem,
    TrashFilter,
    TrashKind,
    TrashPage,
    merge,
)
from wiredex.trash.domain.values import WorkspaceId

# How many records a filtered read takes from the bins at a time while it looks for matches.
SCAN_BATCH = MAX_PAGE_SIZE


class ListTrash:
    """One page of the trash, newest first across every kind (requirements 4.1 to 4.3, 4.5),
    narrowed by a kind, a fragment of a name or detail, or both.

    Each bin is asked for one more record than the page holds, before the same position, so the
    merge can tell whether anything is left for a next page (decision 9). A kind asks its own bin
    alone. The text is matched here, on what the bins answer, since a unit's detail is its part's
    name, which only the catalog knows: the bins are read a batch at a time, from the cursor on,
    until the page is full and one more match says a next page exists, or they run out.
    """

    def __init__(self, bins: Sequence[TrashBin]) -> None:
        self._bins = tuple(bins)

    async def __call__(
        self,
        workspace_id: WorkspaceId,
        cursor: TrashCursor | None,
        limit: int,
        narrowing: TrashFilter | None = None,
    ) -> TrashPage:
        wanted = narrowing or TrashFilter()
        bins = [trash_bin for trash_bin in self._bins if wanted.keeps(trash_bin.kind)]
        before = None if cursor is None else cursor.position
        if wanted.text is None:
            return await _read(bins, workspace_id, before, limit)
        kept: list[TrashedItem] = []
        while True:
            batch = await _read(bins, workspace_id, before, SCAN_BATCH)
            kept.extend(item for item in batch.items if wanted.matches(item))
            if len(kept) > limit:
                page = tuple(kept[:limit])
                return TrashPage(page, TrashCursor(page[-1].position))
            if batch.next is None:
                return TrashPage(tuple(kept), None)
            before = batch.next.position


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


async def _read(
    bins: Sequence[TrashBin],
    workspace_id: WorkspaceId,
    before: TrashPosition | None,
    limit: int,
) -> TrashPage:
    """The newest `limit` records of the bins before the position, asking each for one more."""
    pages = [await trash_bin.page(workspace_id, before, limit + 1) for trash_bin in bins]
    return merge(pages, limit)


def _by_kind(bins: Sequence[TrashBin]) -> Mapping[TrashKind, TrashBin]:
    return {trash_bin.kind: trash_bin for trash_bin in bins}


def _bin_of(bins: Mapping[TrashKind, TrashBin], kind: TrashKind) -> TrashBin:
    found = bins.get(kind)
    if found is None:
        raise TrashItemNotFoundError("nothing of that kind is in the trash")
    return found
