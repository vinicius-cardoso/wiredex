"""One transaction across projects, inventory and catalog, for a build transition.

The one file that sees all three modules (10-build-lifecycle decision 8, requirement 14.1).
Projects declares two ports, `BuildStock` and `BuildParts`, as properties of its
`BuildUnitOfWork`, and imports neither inventory nor catalog. Inventory offers `RevisionStock`
over an `InventoryRepositories`, and catalog `describe_parts` over a `CatalogRepositories`,
each never opening or committing a transaction of its own. This file joins them.

`SqlBuildUnitOfWork` lets the projects unit of work open one session, scope it to the workspace
once and bind its own repositories and 09's `bom_lines`; it then binds `InventoryBuildStock`
and `CatalogBuildParts` on that same session, so one `commit()` keeps a revision's status, its
movements, its balances and its units together, and leaving without it keeps none of them
(requirements 1.3, 1.4). Every repository shares the session `SqlProjectsUnitOfWork` opened,
under the workspace setting that unit of work applied, so row-level security scopes all three
(requirement 11.1). It is the second use of 07's shared-session pattern, mirroring
`bootstrap/intake.py`.

`InventoryBuildStock` translates ids, types and errors both ways: projects speaks its own
`PartId`, `UnitId`, `LotId`, `LocationId` and `RevisionId`, all bare uuids that are the same
uuids under inventory's names, and inventory's `LocationNotFoundError` and
`ConcurrentStockError` become projects' `UnknownLocationError` and `StockChangedError`, the only
two its checks let through to a write (Error Handling). It is built per unit of work, so the
`LockedStock` it keeps from `available` lives exactly as long as the transaction.
"""

from collections.abc import Collection
from datetime import datetime
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from wiredex.catalog.application.parts import describe_parts
from wiredex.catalog.application.ports import CatalogRepositories
from wiredex.catalog.domain.category import CategoryFlags
from wiredex.catalog.domain.part import PartDefinition
from wiredex.catalog.domain.values import PartDefinitionId
from wiredex.catalog.domain.values import WorkspaceId as CatalogWorkspaceId
from wiredex.catalog.infrastructure.unit_of_work import SqlCatalogRepositories
from wiredex.inventory.application.builds import LockedStock, LotTake, RevisionStock
from wiredex.inventory.application.ports import LockedLot, RevisionUnitRow
from wiredex.inventory.domain.errors import ConcurrentStockError, LocationNotFoundError
from wiredex.inventory.domain.holdings import HeldStock
from wiredex.inventory.domain.unit import Unit, UnitStatus
from wiredex.inventory.domain.values import LocationId as InventoryLocationId
from wiredex.inventory.domain.values import PartId as InventoryPartId
from wiredex.inventory.domain.values import RevisionId as InventoryRevisionId
from wiredex.inventory.domain.values import StockLotId
from wiredex.inventory.domain.values import UnitId as InventoryUnitId
from wiredex.inventory.domain.values import WorkspaceId as InventoryWorkspaceId
from wiredex.inventory.infrastructure.unit_of_work import SqlInventoryRepositories
from wiredex.projects.application.ports import HeldLot, HeldUnit, Holdings, RevisionHolding
from wiredex.projects.domain.lifecycle import (
    StockChangedError,
    Transition,
    UnknownLocationError,
)
from wiredex.projects.domain.reservation import (
    ReservableLot,
    ReservableStock,
    Reservation,
    StockUnit,
)
from wiredex.projects.domain.shortage import PartFacts
from wiredex.projects.domain.values import LocationId, LotId, PartId, RevisionId, UnitId
from wiredex.projects.domain.values import WorkspaceId as ProjectsWorkspaceId
from wiredex.projects.infrastructure.unit_of_work import SqlProjectsUnitOfWork
from wiredex.shared_kernel.application.ports import Clock, IdGenerator


class InventoryBuildStock:
    """Projects' `BuildStock` over inventory's `RevisionStock` (decision 8).

    The `LockedStock` from `available` is kept for the same transaction's `reserve`, so the
    balances the reserve writes are the ones it read (requirement 2.8). A `reserve` with no
    `available` before it is a bug, raised as such.
    """

    def __init__(self, stock: RevisionStock) -> None:
        self._stock = stock
        self._locked: LockedStock | None = None

    async def available(
        self, part_ids: Collection[PartId], named: Collection[UnitId]
    ) -> ReservableStock:
        locked = await self._stock.available(
            [InventoryPartId(part_id) for part_id in part_ids],
            [InventoryUnitId(unit_id) for unit_id in named],
        )
        self._locked = locked
        return _reservable(locked)

    async def reserve(self, revision_id: RevisionId, reservation: Reservation) -> None:
        if self._locked is None:
            raise RuntimeError("reserve() called before available() in this transaction")
        takes = [
            LotTake(
                lot_id=StockLotId(pick.lot_id),
                quantity=pick.quantity,
                unit_ids=tuple(InventoryUnitId(unit_id) for unit_id in pick.unit_ids),
            )
            for pick in reservation.picks
        ]
        await self._stock.reserve(self._locked, InventoryRevisionId(revision_id), takes)

    async def release(self, revision_id: RevisionId) -> datetime:
        return await self._stock.release(InventoryRevisionId(revision_id))

    async def consume(self, revision_id: RevisionId) -> datetime:
        return await self._stock.consume(InventoryRevisionId(revision_id))

    async def return_to(self, revision_id: RevisionId, location_id: LocationId) -> datetime:
        try:
            return await self._stock.return_to(
                InventoryRevisionId(revision_id), InventoryLocationId(location_id)
            )
        except LocationNotFoundError as error:
            # A dismantle naming a location the workspace doesn't hold (requirements 6.1, 11.2).
            raise UnknownLocationError(str(error), Transition.DISMANTLE) from error
        except ConcurrentStockError as error:
            # Only two first writes to one fresh return lot can race it; pressing again clears
            # it, so nothing retries (decision 12).
            raise StockChangedError(str(error), Transition.DISMANTLE) from error

    async def holdings(self, revision_id: RevisionId) -> Holdings:
        return _holdings(await self._stock.holdings(InventoryRevisionId(revision_id)))

    async def holdings_of_part(self, part_id: PartId) -> list[RevisionHolding]:
        found = await self._stock.holdings_of_part(InventoryPartId(part_id))
        return [
            RevisionHolding(
                revision_id=RevisionId(holding.revision_id),
                reserved=holding.reserved,
                consumed=holding.consumed,
            )
            for holding in found
        ]

    async def units_of(self, revision_id: RevisionId) -> list[HeldUnit]:
        rows = await self._stock.units_of(InventoryRevisionId(revision_id))
        return [_held_unit(row) for row in rows]


class CatalogBuildParts:
    """Projects' `BuildParts` over catalog's `describe_parts`, on the transition's session.

    The mirror of `bootstrap/parts.py`'s `CatalogPartLookup`, but over a `CatalogRepositories`
    bound to the projects unit of work's session rather than a `DescribeParts` that opens its
    own: a build transition describes its BOM's parts inside its one transaction (decision 8).
    A part the workspace doesn't hold is left out, which projects reads as an unknown part.
    """

    def __init__(self, repositories: CatalogRepositories) -> None:
        self._repositories = repositories

    async def describe(self, part_ids: Collection[PartId]) -> dict[PartId, PartFacts]:
        described = await describe_parts(
            self._repositories, [PartDefinitionId(part_id) for part_id in part_ids]
        )
        return {
            PartId(part_id): _facts(description.part, description.flags)
            for part_id, description in described.items()
        }


class SqlBuildUnitOfWork(SqlProjectsUnitOfWork):
    """The projects unit of work with inventory's stock and catalog's parts on its session.

    A `BuildUnitOfWork`: the base opens the session, sets `app.workspace_id` for the
    transaction and binds projects' repositories and 09's `bom_lines`. Inventory's and
    catalog's repositories then join that same session under the same workspace, wrapped as
    `InventoryBuildStock` and `CatalogBuildParts`, so one `commit()` covers the rows of all
    three modules and row-level security scopes every read and write under one setting
    (requirements 1.3, 11.1). Commit and rollback stay 08's.
    """

    stock: InventoryBuildStock
    parts: CatalogBuildParts

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        workspace_id: ProjectsWorkspaceId,
        clock: Clock,
        ids: IdGenerator,
    ) -> None:
        super().__init__(session_factory, workspace_id, ids)
        self._clock = clock

    async def __aenter__(self) -> Self:
        await super().__aenter__()
        # The same UUID under each module's own name: neither module imports the other's
        # domain (requirement 14.1).
        inventory = SqlInventoryRepositories(self.session, InventoryWorkspaceId(self._workspace))
        revision_stock = RevisionStock(
            inventory, InventoryWorkspaceId(self._workspace), self._clock, self._ids
        )
        self.stock = InventoryBuildStock(revision_stock)
        catalog = SqlCatalogRepositories(self.session, CatalogWorkspaceId(self._workspace))
        self.parts = CatalogBuildParts(catalog)
        return self


def _reservable(locked: LockedStock) -> ReservableStock:
    """`LockedStock` in projects' terms: each lot's on hand less reserved, each unit's status
    as `in_stock`, `now` and `changed` passed through (decision 8)."""
    return ReservableStock(
        lots=tuple(_reservable_lot(row) for row in locked.lots),
        units=tuple(_stock_unit(unit) for unit in locked.units),
        named={UnitId(unit_id): _stock_unit(unit) for unit_id, unit in locked.named.items()},
        now=locked.now,
        changed=locked.changed,
    )


def _reservable_lot(row: LockedLot) -> ReservableLot:
    return ReservableLot(
        lot_id=LotId(row.lot.id),
        part_id=PartId(row.lot.part_id),
        location_code=row.location_code,
        available=int(row.balance.available),
    )


def _stock_unit(unit: Unit) -> StockUnit:
    return StockUnit(
        unit_id=UnitId(unit.id),
        code=str(unit.code),
        part_id=PartId(unit.part_id),
        lot_id=LotId(unit.lot_id),
        in_stock=unit.status is UnitStatus.IN_STOCK,
    )


def _holdings(held: HeldStock) -> Holdings:
    return Holdings(
        reserved=tuple(
            HeldLot(
                part_id=PartId(holding.part_id),
                location_id=LocationId(holding.location_id),
                location_code=holding.location_code,
                quantity=holding.quantity,
            )
            for holding in held.reserved
        ),
        consumed={PartId(part_id): quantity for part_id, quantity in held.consumed.items()},
    )


def _held_unit(row: RevisionUnitRow) -> HeldUnit:
    return HeldUnit(
        unit_id=UnitId(row.unit.id),
        code=str(row.unit.code),
        part_id=PartId(row.unit.part_id),
        location_code=row.location_code,
    )


def _facts(part: PartDefinition, flags: CategoryFlags) -> PartFacts:
    # A part and its category's resolved flags, in projects' words, as `bootstrap/parts.py`'s
    # `CatalogPartLookup` builds them.
    return PartFacts(
        part_id=PartId(part.id),
        name=str(part.name),
        manufacturer=_text(part.manufacturer),
        mpn=_text(part.mpn),
        package=_text(part.package),
        tracked_individually=flags.tracked_individually,
        not_stocked=flags.not_stocked,
    )


def _text(value: object) -> str | None:
    return None if value is None else str(value)
