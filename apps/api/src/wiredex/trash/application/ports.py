"""What the trash asks of the modules whose records it holds: one bin per kind (decision 8).

The trash imports no module. Each bin is built in `bootstrap/trash.py` over its module's own
use cases, which decide what restoring and deleting for good mean; the trash only lists, merges
and dispatches. A bin runs its module's unit of work and closes it before it answers, so the
trash never holds two at once.
"""

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from wiredex.shared_kernel.domain.trash import TrashPosition
from wiredex.trash.domain.trash import TrashedItem, TrashKind
from wiredex.trash.domain.values import WorkspaceId


class TrashBin(Protocol):
    """One kind's share of the trash, answered by the module that owns the kind."""

    @property
    def kind(self) -> TrashKind:
        """The kind of record this bin holds, which picks it for a restore or a delete."""
        ...

    async def page(
        self, workspace_id: WorkspaceId, before: TrashPosition | None, limit: int
    ) -> Sequence[TrashedItem]:
        """The bin's records moved to the trash before the position, newest first, at most
        `limit` of them, in one read whatever their number (requirement 10.3)."""
        ...

    async def restore(self, workspace_id: WorkspaceId, item_id: UUID) -> None:
        """The record back as it was; `TrashItemNotFoundError` when it isn't in this bin."""
        ...

    async def delete(self, workspace_id: WorkspaceId, item_id: UUID) -> None:
        """The record deleted for good with its contents; `TrashItemNotFoundError` when it
        isn't in this bin."""
        ...

    async def empty(self, workspace_id: WorkspaceId) -> None:
        """Every record in this bin deleted for good, in the module's one transaction."""
        ...
