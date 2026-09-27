"""Wire the inventory module: the use cases over Postgres, and the `Parts` port over catalog.

`inventory` imports neither catalog nor identity (the independence contract forbids it): this
composition root is the one place that knows both, so it implements the `Parts` port here and
hands it to the use cases (design §3). `CatalogParts` asks catalog's `GetPart` whether a part
exists and `GetCategorySchema` how its category is tracked, and answers with `PartStockInfo`,
so inventory learns both facts in one call and never sees a `Category`.
"""

from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from wiredex.catalog.application.attributes import GetCategorySchema
from wiredex.catalog.application.parts import GetPart
from wiredex.catalog.domain.errors import CategoryNotFoundError, PartNotFoundError
from wiredex.catalog.domain.values import CategoryId, PartDefinitionId
from wiredex.catalog.domain.values import WorkspaceId as CatalogWorkspaceId
from wiredex.catalog.infrastructure.unit_of_work import SqlCatalogUnitOfWork
from wiredex.inventory.api.router import InventoryUseCases
from wiredex.inventory.application.locations import (
    CreateLocation,
    DeleteLocation,
    ListLocations,
    MoveLocation,
    RenameLocation,
)
from wiredex.inventory.application.movements import AdjustStock, MoveStock, ReceiveStock
from wiredex.inventory.application.ports import PartStockInfo
from wiredex.inventory.application.stock import PartStock, PartTotals
from wiredex.inventory.domain.values import PartId, WorkspaceId
from wiredex.inventory.infrastructure.unit_of_work import SqlInventoryUnitOfWork
from wiredex.shared_kernel.infrastructure.clock import SystemClock
from wiredex.shared_kernel.infrastructure.ids import Uuid7Generator

type SessionFactory = async_sessionmaker[AsyncSession]


class CatalogParts:
    """The `Parts` port over catalog's `GetPart` and resolved tracking flag (design §3).

    A part catalog doesn't know — deleted, never created, or another workspace's — is a
    `PartNotFoundError`, which becomes `PartStockInfo(exists=False)`: inventory reads that as
    a 404 receive (requirement 4.2). A part that exists carries its category's resolved
    "tracked individually" answer, which a lot receive refuses with 422 (requirement 6.3).
    The two catalog use cases are read-only, so one call describes the part without a write.
    """

    def __init__(self, get_part: GetPart, get_category_schema: GetCategorySchema) -> None:
        self._get_part = get_part
        self._get_category_schema = get_category_schema

    async def describe(self, workspace_id: WorkspaceId, part_id: PartId) -> PartStockInfo:
        # Inventory's WorkspaceId and catalog's are the same UUID under two names, one per
        # module: neither module imports the other's domain (design §3).
        catalog_workspace = CatalogWorkspaceId(workspace_id)
        try:
            view = await self._get_part(catalog_workspace, PartDefinitionId(part_id))
        except PartNotFoundError:
            return PartStockInfo(exists=False, tracked_individually=False)
        tracked = await self._resolve_tracking(catalog_workspace, view.part.category_id)
        return PartStockInfo(exists=True, tracked_individually=tracked)

    async def _resolve_tracking(
        self, workspace_id: CatalogWorkspaceId, category_id: CategoryId
    ) -> bool:
        """The category's resolved "tracked individually" answer, along its ancestor chain.

        `GetCategorySchema` resolves the flag with the same recursive read the schema uses
        (design's catalog change). A category racing a delete between the two reads is
        treated as untracked — lot-counted — the safe default the chain resolves to anyway.
        """
        try:
            resolved = await self._get_category_schema(workspace_id, category_id)
        except CategoryNotFoundError:
            return False
        return resolved.tracked_individually_resolved


def inventory_use_cases(session_factory: SessionFactory) -> InventoryUseCases:
    """The inventory use cases, wired to Postgres, with the `Parts` port over catalog."""

    def unit_of_work(workspace_id: WorkspaceId) -> SqlInventoryUnitOfWork:
        # One unit of work per workspace, as catalog's and files' are: the id reaches both of
        # ADR 0007's gates — the repositories filter on it and Postgres reads it in its
        # policies (design §3).
        return SqlInventoryUnitOfWork(session_factory, workspace_id)

    parts = CatalogParts(
        GetPart(_catalog_unit_of_work(session_factory)),
        GetCategorySchema(_catalog_unit_of_work(session_factory)),
    )
    clock, ids = SystemClock(), Uuid7Generator()
    return InventoryUseCases(
        create_location=CreateLocation(unit_of_work, clock, ids),
        rename_location=RenameLocation(unit_of_work),
        move_location=MoveLocation(unit_of_work),
        delete_location=DeleteLocation(unit_of_work),
        list_locations=ListLocations(unit_of_work),
        receive_stock=ReceiveStock(unit_of_work, parts, clock, ids),
        adjust_stock=AdjustStock(unit_of_work, parts, clock, ids),
        move_stock=MoveStock(unit_of_work, clock, ids),
        part_stock=PartStock(unit_of_work),
        part_totals=PartTotals(unit_of_work),
    )


def _catalog_unit_of_work(
    session_factory: SessionFactory,
) -> Callable[[CatalogWorkspaceId], SqlCatalogUnitOfWork]:
    return lambda workspace_id: SqlCatalogUnitOfWork(session_factory, workspace_id)
