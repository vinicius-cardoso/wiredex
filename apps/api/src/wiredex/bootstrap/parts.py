"""Catalog's answers about parts, in the words of the modules that ask for them.

`inventory` and `projects` import no catalog code (the independence contract forbids it), so
the composition root answers their questions about parts here, over one catalog use case,
`DescribeParts`: the part and its category's resolved flags, several parts in two reads
(09's decision 14). Each adapter translates ids and workspace ids between the modules' own
`NewType`s, and reads a part catalog doesn't hold as absent rather than raising.
"""

from wiredex.catalog.application.parts import DescribeParts
from wiredex.catalog.domain.values import PartDefinitionId
from wiredex.catalog.domain.values import WorkspaceId as CatalogWorkspaceId
from wiredex.inventory.application.ports import PartStockInfo
from wiredex.inventory.domain.values import PartId as InventoryPartId
from wiredex.inventory.domain.values import WorkspaceId as InventoryWorkspaceId


class CatalogParts:
    """Inventory's `Parts` port over catalog's `DescribeParts`.

    A part catalog doesn't know — deleted, never created, or another workspace's — answers
    `exists=False`, which inventory reads as a 404 receive (requirement 4.2). A part that
    exists carries both of its category's resolved flags: tracked individually refuses a lot
    receive (6.3), and not stocked refuses any receipt (09's requirement 2.1). One catalog
    transaction describes the part, where `GetPart` and `GetCategorySchema` took two and read
    a schema and a pin count nothing used.
    """

    def __init__(self, describe_parts: DescribeParts) -> None:
        self._describe_parts = describe_parts

    async def describe(
        self, workspace_id: InventoryWorkspaceId, part_id: InventoryPartId
    ) -> PartStockInfo:
        # The same UUIDs under each module's own names: neither imports the other's domain.
        catalog_id = PartDefinitionId(part_id)
        described = await self._describe_parts(CatalogWorkspaceId(workspace_id), [catalog_id])
        found = described.get(catalog_id)
        if found is None:
            return PartStockInfo(exists=False, tracked_individually=False, not_stocked=False)
        return PartStockInfo(
            exists=True,
            tracked_individually=found.flags.tracked_individually,
            not_stocked=found.flags.not_stocked,
        )
