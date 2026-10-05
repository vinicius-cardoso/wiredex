"""Inventory's share of the trash: the units in it, and bringing one back or deleting it for good.

Moving a unit to the trash is `DeleteUnit`, for a retired unit only (16-soft-delete-and-trash,
decision 4). What follows it is here, one use case each, which bootstrap wraps in the trash
module's bin for units (decision 8). Restoring and deleting for good each lock the unit first, so
the two take turns and the second finds nothing (decision 10). A unit comes back retired, as it
went, into the lot it pointed at, which is never deleted; deleted for good, it leaves its
movements and its flashes behind, as deleting a unit did before.
"""

from wiredex.inventory.application.ports import InventoryUnitOfWork
from wiredex.inventory.application.units import UnitOfWorkFactory
from wiredex.inventory.domain.errors import UnitNotFoundError
from wiredex.inventory.domain.unit import Unit
from wiredex.inventory.domain.values import PartId, UnitId, WorkspaceId
from wiredex.shared_kernel.domain.trash import TrashedSlice


class ListTrashedUnits:
    """The newest `count` units in the trash, only those whose code holds the text or whose
    part is one of `part_ids` when there is a text, and how many match in all (requirement
    4.1). The trash names the parts whose name holds the text, which only the catalog knows."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(
        self,
        workspace_id: WorkspaceId,
        count: int,
        text: str | None = None,
        part_ids: frozenset[PartId] = frozenset(),
    ) -> TrashedSlice[Unit]:
        async with self._unit_of_work(workspace_id) as work:
            return await work.units.trashed(count, text, part_ids)


class RestoreUnit:
    """A unit back from the trash, retired as it was (requirement 5.1)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId, unit_id: UnitId) -> None:
        async with self._unit_of_work(workspace_id) as work:
            unit = await _in_trash(work, unit_id)
            unit.restore_from_trash()
            await work.commit()


class DeleteUnitForGood:
    """A unit in the trash deleted, its movements and flashes kept (requirements 6.1, 6.3)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId, unit_id: UnitId) -> None:
        async with self._unit_of_work(workspace_id) as work:
            unit = await _in_trash(work, unit_id)
            await work.units.remove(unit)
            await work.commit()


class EmptyUnitTrash:
    """Every unit in the trash deleted for good, in one statement (requirement 6.4)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId) -> int:
        async with self._unit_of_work(workspace_id) as work:
            emptied = await work.units.empty_trash()
            await work.commit()
            return emptied


async def _in_trash(work: InventoryUnitOfWork, unit_id: UnitId) -> Unit:
    """The unit, locked, if it is in the trash; a 404 for one that isn't, another workspace's
    included (requirements 5.3, 6.2)."""
    unit = await work.units.in_trash(unit_id)
    if unit is None:
        raise UnitNotFoundError("that unit isn't in the trash")
    return unit
