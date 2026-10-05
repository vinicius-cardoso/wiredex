"""Catalog's share of the trash: the parts in it, and bringing one back or deleting it for good.

Moving a part to the trash is `DeletePart` (16-soft-delete-and-trash, decision 4). What follows it
is here, one use case each, which bootstrap wraps in the trash module's bin for parts (decision 8).
Restoring and deleting for good each lock the part first, so the two take turns and the second
finds nothing (decision 10); neither checks anything else, since nothing can point at a part while
it is absent (requirements decision 6).
"""

from wiredex.catalog.application.categories import UnitOfWorkFactory
from wiredex.catalog.application.ports import CatalogUnitOfWork
from wiredex.catalog.domain.errors import PartNotFoundError
from wiredex.catalog.domain.part import PartDefinition
from wiredex.catalog.domain.values import PartDefinitionId, WorkspaceId
from wiredex.shared_kernel.domain.trash import TrashedSlice


class ListTrashedParts:
    """The newest `count` parts in the trash, only those whose name or MPN holds the text when
    there is one, and how many match in all (requirement 4.1)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(
        self, workspace_id: WorkspaceId, count: int, text: str | None = None
    ) -> TrashedSlice[PartDefinition]:
        async with self._unit_of_work(workspace_id) as work:
            return await work.parts.trashed(count, text)


class RestorePart:
    """A part back from the trash with its pinout, as it was (requirement 5.1)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId, part_id: PartDefinitionId) -> None:
        async with self._unit_of_work(workspace_id) as work:
            part = await _in_trash(work, part_id)
            part.restore_from_trash()
            await work.commit()


class DeletePartForGood:
    """A part in the trash deleted with its pinout, as deleting a part did before (6.1)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId, part_id: PartDefinitionId) -> None:
        async with self._unit_of_work(workspace_id) as work:
            part = await _in_trash(work, part_id)
            await work.parts.remove(part)
            await work.commit()


class EmptyPartTrash:
    """Every part in the trash deleted for good, in one statement (requirement 6.4)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId) -> int:
        async with self._unit_of_work(workspace_id) as work:
            emptied = await work.parts.empty_trash()
            await work.commit()
            return emptied


class PartIsKept:
    """Whether the workspace still holds a part, live or in the trash: what the files prune asks
    before it sweeps a part's attachments (16's decision 7)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId, part_id: PartDefinitionId) -> bool:
        async with self._unit_of_work(workspace_id) as work:
            return await work.parts.kept(part_id)


async def _in_trash(work: CatalogUnitOfWork, part_id: PartDefinitionId) -> PartDefinition:
    """The part, locked, if it is in the trash; a 404 for one that isn't, another workspace's
    included (requirements 5.3, 6.2)."""
    part = await work.parts.in_trash(part_id)
    if part is None:
        raise PartNotFoundError("that part isn't in the trash")
    return part
