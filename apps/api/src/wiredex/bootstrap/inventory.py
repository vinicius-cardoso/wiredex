"""Wire the inventory module: the use cases over Postgres, and the `Parts` port over catalog.

`inventory` imports neither catalog nor identity (the independence contract forbids it): this
composition root is the one place that knows both, so it hands the use cases the `Parts` port
`bootstrap/parts.py` builds over catalog's `DescribeParts` (design §3, 09's decision 14), and
inventory learns whether a part exists and how its category counts it in one call, without
ever seeing a `Category`.
"""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.intake import SqlIntakeUnitOfWork
from wiredex.bootstrap.parts import CatalogParts
from wiredex.bootstrap.settings import Settings
from wiredex.catalog.application.parts import DescribeParts, NameParts
from wiredex.catalog.domain.values import WorkspaceId as CatalogWorkspaceId
from wiredex.catalog.infrastructure.unit_of_work import SqlCatalogUnitOfWork
from wiredex.inventory.api.router import InventoryUseCases
from wiredex.inventory.application.imports import ImportSheet, PreviewImport
from wiredex.inventory.application.intake import QuickAdd
from wiredex.inventory.application.locations import (
    CreateLocation,
    DeleteLocation,
    ListLocations,
    MoveLocation,
    RenameLocation,
)
from wiredex.inventory.application.movements import AdjustStock, MoveStock, ReceiveStock
from wiredex.inventory.application.stock import (
    LocationStock,
    PartStock,
    PartTotals,
    RebuildBalances,
)
from wiredex.inventory.application.units import (
    DeleteUnit,
    GetUnit,
    ListUnitsOfLocation,
    ListUnitsOfPart,
    LocateUnits,
    MoveUnit,
    NameUnitParts,
    ReceiveUnits,
    RelabelUnit,
    RetireUnit,
    SearchUnits,
    UnretireUnit,
)
from wiredex.inventory.domain.values import WorkspaceId
from wiredex.inventory.infrastructure.unit_of_work import SqlInventoryUnitOfWork
from wiredex.shared_kernel.infrastructure.clock import SystemClock
from wiredex.shared_kernel.infrastructure.ids import Uuid7Generator

type SessionFactory = async_sessionmaker[AsyncSession]


def inventory_use_cases(session_factory: SessionFactory) -> InventoryUseCases:
    """The inventory use cases, wired to Postgres, with the `Parts` port over catalog."""

    def unit_of_work(workspace_id: WorkspaceId) -> SqlInventoryUnitOfWork:
        # One unit of work per workspace, as catalog's and files' are: the id reaches both of
        # ADR 0007's gates — the repositories filter on it and Postgres reads it in its
        # policies (design §3).
        return SqlInventoryUnitOfWork(session_factory, workspace_id)

    catalog_unit_of_work = _catalog_unit_of_work(session_factory)
    parts = CatalogParts(DescribeParts(catalog_unit_of_work), NameParts(catalog_unit_of_work))
    clock, ids = SystemClock(), Uuid7Generator()

    def intake_unit_of_work(workspace_id: WorkspaceId) -> SqlIntakeUnitOfWork:
        # Inventory's unit of work with the catalog bound to its session, so a quick-add or a
        # sheet defines its parts and receives their stock in one transaction (07's design
        # decision 2).
        return SqlIntakeUnitOfWork(session_factory, workspace_id, clock, ids)

    # The unit move delegates its stock effect to the same two-row MOVE the lot move uses, so
    # both write one `move_group` of quantity 1; the unit use cases ride the same unit-of-work
    # factory and `Parts` port, no new cross-module wiring (design's Bootstrap and CLI).
    move_stock = MoveStock(unit_of_work, parts, clock, ids)
    # Quick-add and import receive through these same two, calling `perform` inside the
    # intake transaction, so intake's stock goes the way the dialogs' does (requirement 8.6).
    receive_stock = ReceiveStock(unit_of_work, parts, clock, ids)
    receive_units = ReceiveUnits(unit_of_work, parts, clock, ids)
    return InventoryUseCases(
        create_location=CreateLocation(unit_of_work, clock, ids),
        rename_location=RenameLocation(unit_of_work),
        move_location=MoveLocation(unit_of_work),
        delete_location=DeleteLocation(unit_of_work),
        list_locations=ListLocations(unit_of_work),
        receive_stock=receive_stock,
        adjust_stock=AdjustStock(unit_of_work, parts, clock, ids),
        move_stock=move_stock,
        part_stock=PartStock(unit_of_work),
        part_totals=PartTotals(unit_of_work),
        location_stock=LocationStock(unit_of_work, parts),
        receive_units=receive_units,
        relabel_unit=RelabelUnit(unit_of_work),
        retire_unit=RetireUnit(unit_of_work, clock, ids),
        unretire_unit=UnretireUnit(unit_of_work, clock, ids),
        move_unit=MoveUnit(unit_of_work, move_stock, clock, ids),
        delete_unit=DeleteUnit(unit_of_work, clock),
        get_unit=GetUnit(unit_of_work),
        list_units_of_part=ListUnitsOfPart(unit_of_work),
        list_units_of_location=ListUnitsOfLocation(unit_of_work),
        search_units=SearchUnits(unit_of_work),
        locate_units=LocateUnits(unit_of_work),
        name_unit_parts=NameUnitParts(parts),
        quick_add=QuickAdd(intake_unit_of_work, receive_stock, receive_units),
        preview_import=PreviewImport(intake_unit_of_work),
        import_sheet=ImportSheet(intake_unit_of_work, receive_stock, receive_units),
    )


def _catalog_unit_of_work(
    session_factory: SessionFactory,
) -> Callable[[CatalogWorkspaceId], SqlCatalogUnitOfWork]:
    return lambda workspace_id: SqlCatalogUnitOfWork(session_factory, workspace_id)


@asynccontextmanager
async def rebuild_balances_use_case(settings: Settings) -> AsyncIterator[RebuildBalances]:
    """RebuildBalances over Postgres, for one run of `wiredex stock rebuild` (ADR 0002).

    A manual repair tool, not a nightly job: it streams a workspace's whole ledger and
    rewrites its projection from the truth (requirement 5.2). The caller runs it once per
    workspace, so each bench is rebuilt in its own transaction under its own isolation
    (requirement 5.3), the same files-style own-engine pattern the prune and clear use.
    """
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)

    def inventory_unit_of_work(workspace_id: WorkspaceId) -> SqlInventoryUnitOfWork:
        return SqlInventoryUnitOfWork(session_factory, workspace_id)

    try:
        yield RebuildBalances(inventory_unit_of_work)
    finally:
        await engine.dispose()
