"""What the trash asks of the modules whose records it holds: one bin per kind (decision 8).

The trash imports no module. Each bin is built in `bootstrap/trash.py` over its module's own
use cases, which decide what restoring and deleting for good mean; the trash only lists, merges
and dispatches. A bin runs its module's unit of work and closes it before it answers, so the
trash never holds two at once.
"""

from typing import Protocol
from uuid import UUID

from wiredex.shared_kernel.domain.trash import TrashedSlice
from wiredex.trash.domain.trash import TrashedItem, TrashKind
from wiredex.trash.domain.values import WorkspaceId


class TrashBin(Protocol):
    """One kind's share of the trash, answered by the module that owns the kind."""

    @property
    def kind(self) -> TrashKind:
        """The kind of record this bin holds, which picks it for a restore or a delete."""
        ...

    async def newest(
        self, workspace_id: WorkspaceId, count: int, text: str | None
    ) -> TrashedSlice[TrashedItem]:
        """The bin's newest `count` records whose name or detail holds the text, case aside,
        newest first with the id breaking ties, and how many match in all; every record when
        there is no text. The records and their total come from one read of the module's,
        whatever their number (requirement 10.3)."""
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
