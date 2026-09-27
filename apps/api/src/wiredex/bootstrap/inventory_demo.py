"""Wiring for the inventory half of `wiredex demo reset`: the sample locations and stock.

The composition root is the only place that knows both catalog and inventory (as `_reset` and
`_prune` in cli.py already are), which is what keeps the two modules from importing each other.
It resolves each sample part's fresh id from catalog — a reset mints new ids — and builds the
`Parts` port inventory receives through over catalog's `GetPart` plus the resolved tracking
flag, the files-style pattern. Kept out of `bootstrap/inventory.py` on purpose: this is only
the demo's wiring, next to `restore_sample_catalog_use_case`.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.settings import Settings
from wiredex.catalog.application.attributes import GetCategorySchema
from wiredex.catalog.application.categories import UnitOfWorkFactory as CatalogUnitOfWorkFactory
from wiredex.catalog.application.parts import GetPart, ListParts
from wiredex.catalog.application.ports import PartQuery
from wiredex.catalog.domain.errors import PartNotFoundError
from wiredex.catalog.domain.values import PartDefinitionId
from wiredex.catalog.domain.values import WorkspaceId as CatalogWorkspaceId
from wiredex.catalog.infrastructure.unit_of_work import SqlCatalogUnitOfWork
from wiredex.inventory.application.demo import RestoreSampleInventory, part_ids_by_mpn
from wiredex.inventory.application.locations import CreateLocation
from wiredex.inventory.application.movements import ReceiveStock
from wiredex.inventory.application.ports import Parts, PartStockInfo
from wiredex.inventory.application.units import ReceiveUnits
from wiredex.inventory.domain.values import PartId
from wiredex.inventory.domain.values import WorkspaceId as InventoryWorkspaceId
from wiredex.inventory.infrastructure.unit_of_work import SqlInventoryUnitOfWork
from wiredex.shared_kernel.infrastructure.clock import SystemClock
from wiredex.shared_kernel.infrastructure.ids import Uuid7Generator


class CatalogParts(Parts):
    """The inventory `Parts` port over catalog's `GetPart` and the resolved tracking flag.

    A part the catalog doesn't know answers `exists=False` (a 404 receive); a part whose
    category resolves to tracked-individually answers `tracked_individually=True` (a 422 lot
    receive). Inventory never sees a `Category`; catalog is reached only here, in the
    composition root (design §3). The same shape `bootstrap/inventory.py` will build for the
    web app; this one serves the demo reset's own engine.
    """

    def __init__(self, get_part: GetPart, get_schema: GetCategorySchema) -> None:
        self._get_part = get_part
        self._get_schema = get_schema

    async def describe(self, workspace_id: InventoryWorkspaceId, part_id: PartId) -> PartStockInfo:
        catalog_workspace = CatalogWorkspaceId(workspace_id)
        try:
            view = await self._get_part(catalog_workspace, PartDefinitionId(part_id))
        except PartNotFoundError:
            return PartStockInfo(exists=False, tracked_individually=False)
        schema = await self._get_schema(catalog_workspace, view.part.category_id)
        return PartStockInfo(exists=True, tracked_individually=schema.tracked_individually_resolved)


@asynccontextmanager
async def restore_sample_inventory_use_case(
    settings: Settings,
) -> AsyncIterator[RestoreSampleInventory]:
    """RestoreSampleInventory over Postgres, for one run of `wiredex demo reset` (ADR 0011).

    Runs after catalog's parts are restored (requirement 8.6): the sample part ids are read
    from catalog per workspace, so a bench's stock points at the parts that reset just wrote.
    """
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)

    def inventory_unit_of_work(workspace_id: InventoryWorkspaceId) -> SqlInventoryUnitOfWork:
        return SqlInventoryUnitOfWork(session_factory, workspace_id)

    clock, ids = SystemClock(), Uuid7Generator()
    catalog_unit_of_work: CatalogUnitOfWorkFactory = lambda workspace_id: SqlCatalogUnitOfWork(  # noqa: E731
        session_factory, workspace_id
    )
    parts = CatalogParts(
        GetPart(catalog_unit_of_work),
        GetCategorySchema(catalog_unit_of_work),
    )
    list_parts = ListParts(catalog_unit_of_work)
    try:
        yield RestoreSampleInventory(
            inventory_unit_of_work,
            CreateLocation(inventory_unit_of_work, clock, ids),
            ReceiveStock(inventory_unit_of_work, parts, clock, ids),
            ReceiveUnits(inventory_unit_of_work, parts, clock, ids),
            lambda workspace_id: _sample_part_ids(list_parts, workspace_id),
        )
    finally:
        await engine.dispose()


async def _sample_part_ids(
    list_parts: ListParts, workspace_id: InventoryWorkspaceId
) -> dict[str, PartId]:
    """The demo bench's parts as a mapping from MPN to id, one page (the sample is tiny).

    Read after catalog restored its parts, so the ids are the ones this reset minted; the
    inventory sample stock names its parts by MPN, which is stable across resets while the id
    is not (requirement 8.6).
    """
    page = await list_parts(CatalogWorkspaceId(workspace_id), PartQuery())
    return part_ids_by_mpn(
        [(None if part.mpn is None else part.mpn.value, PartId(part.id)) for part in page.items]
    )
