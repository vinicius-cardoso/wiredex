"""Wire the projects module: every use case over Postgres, and its ports over the others.

`projects` imports neither catalog nor inventory (the independence contract): a BOM asks
about its parts through `PartLookup` and about their stock through `StockLevels`, and this
composition root answers both, over catalog's `DescribeParts` (`bootstrap/parts.py`) and
inventory's `AvailableStock` (09's decision 1). Each answers in its own module's transaction.
`files` asks projects whether a project or a revision exists through `bootstrap/files.py`,
with `GetProject` and `GetRevision` (08's decision 12). A fork gives the new revision the
firmware its source runs through `bootstrap/fork.py`, in the fork's own transaction (13's
decision 4).
"""

from collections.abc import Callable, Sequence

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from wiredex.bootstrap.build import SqlBuildUnitOfWork
from wiredex.bootstrap.fork import SqlForkUnitOfWork
from wiredex.bootstrap.netlist import SqlNetlistUnitOfWork
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
from wiredex.projects.application.lifecycle import (
    BuildRevision,
    CancelReservation,
    DismantleRevision,
    GetLifecycle,
    GetRevisionRef,
    ListPartHoldings,
    ReserveRevision,
)
from wiredex.projects.application.netlist import (
    AddNet,
    GetNetlist,
    GetPinUsage,
    RemoveNet,
    UpdateNet,
)
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
from wiredex.shared_kernel.application.ports import IdGenerator
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

    def build_unit_of_work(workspace_id: WorkspaceId) -> SqlBuildUnitOfWork:
        # A transition's unit of work: 08's projects session, with inventory's stock and
        # catalog's parts bound on it, so one commit covers all three modules (decision 8).
        return SqlBuildUnitOfWork(session_factory, workspace_id, clock, ids)

    def netlist_unit_of_work(workspace_id: WorkspaceId) -> SqlNetlistUnitOfWork:
        # A netlist's unit of work: 08's projects session with catalog's parts and pins bound
        # on it, so a write checks pins against the BOM it locked (11's decision 1).
        return SqlNetlistUnitOfWork(session_factory, workspace_id, ids)

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
        delete_project=DeleteProject(unit_of_work, clock),
        get_project=GetProject(unit_of_work),
        list_projects=ListProjects(unit_of_work),
        list_project_tags=ListProjectTags(unit_of_work),
        add_revision=AddRevision(unit_of_work, clock, ids),
        fork_revision=ForkRevision(_fork_unit_of_work(session_factory, ids), clock, ids),
        update_revision=UpdateRevision(unit_of_work, clock),
        delete_revision=DeleteRevision(unit_of_work, clock),
        get_revision=GetRevision(unit_of_work),
        get_bom=GetBom(unit_of_work, parts, stock),
        add_bom_line=AddBomLine(unit_of_work, parts, clock, ids),
        update_bom_line=UpdateBomLine(unit_of_work, parts, clock),
        remove_bom_line=RemoveBomLine(unit_of_work, clock),
        # The lifecycle runs over `SqlBuildUnitOfWork`: a transition is one transaction across
        # projects, inventory and catalog on one session (decision 8).
        reserve_revision=ReserveRevision(build_unit_of_work),
        cancel_reservation=CancelReservation(build_unit_of_work),
        build_revision=BuildRevision(build_unit_of_work),
        dismantle_revision=DismantleRevision(build_unit_of_work),
        get_lifecycle=GetLifecycle(build_unit_of_work),
        get_revision_ref=GetRevisionRef(build_unit_of_work),
        list_part_holdings=ListPartHoldings(build_unit_of_work),
        get_netlist=GetNetlist(netlist_unit_of_work),
        add_net=AddNet(netlist_unit_of_work, clock, ids),
        update_net=UpdateNet(netlist_unit_of_work, clock),
        remove_net=RemoveNet(netlist_unit_of_work, clock),
        get_pin_usage=GetPinUsage(netlist_unit_of_work),
    )


def _fork_unit_of_work(
    session_factory: SessionFactory, ids: IdGenerator
) -> Callable[[WorkspaceId], SqlForkUnitOfWork]:
    # A fork's unit of work: 08's projects session with firmware's links bound on it, so the
    # fork runs the firmware its source runs, copied after its BOM and nets in the fork's one
    # transaction (13's decision 4).
    return lambda workspace_id: SqlForkUnitOfWork(session_factory, workspace_id, ids)
