"""Catalog's answers about parts, in the words of the modules that ask for them.

`inventory` and `projects` import no catalog code (the independence contract forbids it), so
the composition root answers their questions about parts here, over one catalog use case,
`DescribeParts`: the part and its category's resolved flags, several parts in two reads
(09's decision 14). Each adapter translates ids and workspace ids between the modules' own
`NewType`s, and reads a part catalog doesn't hold as absent rather than raising.
"""

from collections.abc import Sequence

from wiredex.catalog.application.parts import DescribeParts, PartDescription
from wiredex.catalog.domain.values import PartDefinitionId
from wiredex.catalog.domain.values import WorkspaceId as CatalogWorkspaceId
from wiredex.inventory.application.ports import PartStockInfo
from wiredex.inventory.domain.values import PartId as InventoryPartId
from wiredex.inventory.domain.values import WorkspaceId as InventoryWorkspaceId
from wiredex.projects.domain.shortage import PartFacts
from wiredex.projects.domain.values import PartId as ProjectsPartId
from wiredex.projects.domain.values import WorkspaceId as ProjectsWorkspaceId


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


class CatalogPartLookup:
    """Projects' `PartLookup` over catalog's `DescribeParts`.

    Every part a BOM names, in the one catalog transaction `DescribeParts` opens, so a BOM
    read asks the catalog once whatever its size (09's requirement 12.3). A part catalog
    doesn't hold is left out, which projects reads as an unknown part: refused on a line
    (4.2, 9.3) and shown as such in the report (6.5).
    """

    def __init__(self, describe_parts: DescribeParts) -> None:
        self._describe_parts = describe_parts

    async def describe(
        self, workspace_id: ProjectsWorkspaceId, part_ids: Sequence[ProjectsPartId]
    ) -> dict[ProjectsPartId, PartFacts]:
        described = await self._describe_parts(
            CatalogWorkspaceId(workspace_id), [PartDefinitionId(part_id) for part_id in part_ids]
        )
        return {
            ProjectsPartId(part_id): _facts(description)
            for part_id, description in described.items()
        }


def _facts(description: PartDescription) -> PartFacts:
    part = description.part
    return PartFacts(
        part_id=ProjectsPartId(part.id),
        name=str(part.name),
        manufacturer=_text(part.manufacturer),
        mpn=_text(part.mpn),
        package=_text(part.package),
        tracked_individually=description.flags.tracked_individually,
        not_stocked=description.flags.not_stocked,
    )


def _text(value: object) -> str | None:
    return None if value is None else str(value)
