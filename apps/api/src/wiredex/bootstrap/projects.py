"""Wire the projects module: every use case over Postgres, and its ports over the others.

`projects` imports neither catalog nor inventory (the independence contract): a BOM asks
about its parts through `PartLookup` and about their stock through `StockLevels`, and this
composition root answers both, over catalog's `DescribeParts` (`bootstrap/parts.py`) and
inventory's `AvailableStock` (09's decision 1). Each answers in its own module's transaction.
`files` asks projects whether a project or a revision exists through `bootstrap/files.py`,
with `GetProject` and `GetRevision` (08's decision 12).
"""

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from wiredex.bootstrap.parts import CatalogPartLookup
from wiredex.catalog.application.parts import DescribeParts
from wiredex.catalog.domain.values import WorkspaceId as CatalogWorkspaceId
from wiredex.catalog.infrastructure.unit_of_work import SqlCatalogUnitOfWork
from wiredex.inventory.application.stock import AvailableStock
from wiredex.inventory.domain.values import PartId as InventoryPartId
from wiredex.inventory.domain.values import WorkspaceId as InventoryWorkspaceId
from wiredex.inventory.infrastructure.unit_of_work import SqlInventoryUnitOfWork
from wiredex.projects.api.router import ProjectsUseCases
from wiredex.projects.application.bom import AddBomLine, GetBom, RemoveBomLine, UpdateBomLine
from wiredex.projects.application.projects import (
    CreateProject,
    DeleteProject,
    GetProject,
    ListProjects,
    ListProjectTags,
    UpdateProject,
)
from wiredex.projects.application.revisions import (
    AddRevision,
    DeleteRevision,
    ForkRevision,
    GetRevision,
    UpdateRevision,
)
from wiredex.projects.domain.values import PartId, WorkspaceId
from wiredex.projects.infrastructure.unit_of_work import SqlProjectsUnitOfWork
from wiredex.shared_kernel.infrastructure.clock import SystemClock
from wiredex.shared_kernel.infrastructure.ids import Uuid7Generator

type SessionFactory = async_sessionmaker[AsyncSession]


class InventoryStockLevels:
    """Projects' `StockLevels` over inventory's `AvailableStock`: one grouped sum for every
    part of a BOM (09's requirement 12.3). A part no lot holds is left out, which the report
    reads as none available."""

    def __init__(self, available_stock: AvailableStock) -> None:
        self._available_stock = available_stock

    async def available(
        self, workspace_id: WorkspaceId, part_ids: Sequence[PartId]
    ) -> dict[PartId, int]:
        # The same UUIDs under each module's own names: neither imports the other's domain.
        available = await self._available_stock(
            InventoryWorkspaceId(workspace_id), [InventoryPartId(part_id) for part_id in part_ids]
        )
        return {PartId(part_id): count for part_id, count in available.items()}


def projects_use_cases(session_factory: SessionFactory) -> ProjectsUseCases:
    """The projects use cases, wired to Postgres, with the BOM's ports over the others."""

    clock, ids = SystemClock(), Uuid7Generator()

    def unit_of_work(workspace_id: WorkspaceId) -> SqlProjectsUnitOfWork:
        # One unit of work per workspace, as every module's is: the id reaches both of ADR
        # 0007's gates, the repositories' filters and the policies Postgres reads it in.
        return SqlProjectsUnitOfWork(session_factory, workspace_id, ids)

    def catalog_unit_of_work(workspace_id: CatalogWorkspaceId) -> SqlCatalogUnitOfWork:
        return SqlCatalogUnitOfWork(session_factory, workspace_id)

    def inventory_unit_of_work(workspace_id: InventoryWorkspaceId) -> SqlInventoryUnitOfWork:
        return SqlInventoryUnitOfWork(session_factory, workspace_id)

    # Each port builds its own module's use case over that module's unit of work, so a BOM
    # read asks the catalog and the stock in transactions of their own (decision 1).
    parts = CatalogPartLookup(DescribeParts(catalog_unit_of_work))
    stock = InventoryStockLevels(AvailableStock(inventory_unit_of_work))
    return ProjectsUseCases(
        create_project=CreateProject(unit_of_work, clock, ids),
        update_project=UpdateProject(unit_of_work, clock),
        delete_project=DeleteProject(unit_of_work),
        get_project=GetProject(unit_of_work),
        list_projects=ListProjects(unit_of_work),
        list_project_tags=ListProjectTags(unit_of_work),
        add_revision=AddRevision(unit_of_work, clock, ids),
        fork_revision=ForkRevision(unit_of_work, clock, ids),
        update_revision=UpdateRevision(unit_of_work, clock),
        delete_revision=DeleteRevision(unit_of_work, clock),
        get_revision=GetRevision(unit_of_work),
        get_bom=GetBom(unit_of_work, parts, stock),
        add_bom_line=AddBomLine(unit_of_work, parts, clock, ids),
        update_bom_line=UpdateBomLine(unit_of_work, parts, clock),
        remove_bom_line=RemoveBomLine(unit_of_work, clock),
    )
