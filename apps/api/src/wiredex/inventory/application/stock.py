"""Reading a part's stock, and rebuilding the whole projection from the ledger.

`PartStock` answers "how much of this part, and where" — a total and a per-location
breakdown — reading the balance sheet, never the ledger: the projection is what a page shows
(requirement 7.3). A part never received reads as zero and an empty breakdown, not an error
(requirement 7.4).

`RebuildBalances` is the ledger's proof of itself (ADR 0002): it streams the whole ledger,
folds it back into balances with the same domain `apply` the incremental path uses, and
replaces the projection — one transaction per workspace (requirement 5.2). Because it folds
with `Balances.rebuilt_from`, a rebuild reaches the numbers a movement-at-a-time projection
did, balance for balance (requirement 5.3).
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from wiredex.inventory.application.ports import (
    InventoryUnitOfWork,
    LocationLot,
    LotBalance,
    Parts,
    PartStockView,
)
from wiredex.inventory.domain.errors import LocationNotFoundError
from wiredex.inventory.domain.ledger import Balances, StockMovement
from wiredex.inventory.domain.unit import UnitStatus
from wiredex.inventory.domain.values import LocationId, PartId, WorkspaceId

type UnitOfWorkFactory = Callable[[WorkspaceId], InventoryUnitOfWork]


class PartTotals:
    """The total on_hand for a page of parts, in one query (requirements 7.1, 7.2).

    The parts list shows a stock column, and a page of a hundred rows must not read a
    balance per row: `BalanceSheet.totals_by_part` sums them in one grouped query. A part no
    lot has ever held is simply absent from the result — the list reads that as zero.
    """

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(
        self, workspace_id: WorkspaceId, part_ids: Sequence[PartId]
    ) -> dict[PartId, int]:
        async with self._unit_of_work(workspace_id) as work:
            return await work.balances.totals_by_part(part_ids)


@dataclass(frozen=True, slots=True)
class StockCounting:
    """How a part's stock is counted today: `loose` pieces on hand that no unit carries, and
    `units` that aren't retired, in stock, reserved or built into a revision."""

    loose: int = 0
    units: int = 0


class CountStockByKind:
    """For each listed part, how much of its stock is loose and how many units it has: what the
    catalog asks before a part changes between counted in lots and tracked as units, since
    each kind is changed only by its own operations. A part holding neither is absent.

    A lot's `on_hand` includes its in-stock and reserved units (06), so what is left of the
    part's total once those are taken out is loose.
    """

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(
        self, workspace_id: WorkspaceId, part_ids: Sequence[PartId]
    ) -> dict[PartId, StockCounting]:
        if not part_ids:
            return {}
        async with self._unit_of_work(workspace_id) as work:
            totals = await work.balances.totals_by_part(part_ids)
            by_status = await work.units.status_counts(part_ids)
        counted: dict[PartId, StockCounting] = {}
        for part_id in totals.keys() | by_status.keys():
            statuses = by_status.get(part_id, {})
            on_hand = statuses.get(UnitStatus.IN_STOCK, 0) + statuses.get(UnitStatus.RESERVED, 0)
            counting = StockCounting(
                loose=max(0, totals.get(part_id, 0) - on_hand),
                units=on_hand + statuses.get(UnitStatus.IN_USE, 0),
            )
            if counting != StockCounting():
                counted[part_id] = counting
        return counted


class StockedParts:
    """Every part with stock on hand, in one grouped query: what the catalog's search narrows
    by when asked for the parts in stock or out of it, answered through bootstrap. The same
    sum as `PartTotals`, so a part is stocked exactly when the parts list shows stock for it.
    """

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId) -> frozenset[PartId]:
        async with self._unit_of_work(workspace_id) as work:
            return frozenset(await work.balances.stocked_parts())


class AvailableStock:
    """What is available of several parts, summed over each part's lots, in one query.

    `available` is `on_hand - reserved`, stored and CHECKed per balance (ADR 0002), so the
    sum needs no unit logic: a unit-tracked part's lots hold its in-stock units (06). A part
    no lot holds is absent, read as zero. What a bill of materials' shortage report is
    answered from, through bootstrap (09's requirements 6.2, 6.3, 12.3).
    """

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(
        self, workspace_id: WorkspaceId, part_ids: Sequence[PartId]
    ) -> dict[PartId, int]:
        # No ids, no transaction: an empty BOM asks nothing of inventory.
        if not part_ids:
            return {}
        async with self._unit_of_work(workspace_id) as work:
            return await work.balances.available_by_part(part_ids)


class PartStock:
    """A part's totals and its breakdown by location (requirements 7.3, 7.4, 10.3).

    On hand, reserved and available, per location and in total, so a page shows what is set
    aside for builds beside what sits on the shelf (requirement 10.3). The totals are the
    breakdown summed, so the two never disagree: a part in three drawers reports the three
    rows and their sums in one read. A part no lot has ever held reads as zeros and an empty
    breakdown — the honest answer, not a 404 (requirement 7.4).
    """

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId, part_id: PartId) -> PartStockView:
        async with self._unit_of_work(workspace_id) as work:
            breakdown: list[LotBalance] = await work.balances.by_part(part_id)
        total = sum(int(row.on_hand) for row in breakdown)
        reserved = sum(int(row.reserved) for row in breakdown)
        return PartStockView(total=total, reserved=reserved, breakdown=breakdown)


class LocationStock:
    """What a location holds: each lot sitting in it, with its part's name, on hand and
    reserved, by part name, the parts no longer named last (the location's page).

    Two reads whatever the number of lots: the lots with their balances, then every part's
    name through the `Parts` port at once. A location the workspace doesn't hold is a 404
    (`LocationNotFoundError`), never an empty answer. A read: no `commit`.
    """

    def __init__(self, unit_of_work: UnitOfWorkFactory, parts: Parts) -> None:
        self._unit_of_work = unit_of_work
        self._parts = parts

    async def __call__(
        self, workspace_id: WorkspaceId, location_id: LocationId
    ) -> list[LocationLot]:
        async with self._unit_of_work(workspace_id) as work:
            if await work.locations.get(location_id) is None:
                raise LocationNotFoundError("no such location in this workspace")
            holdings = await work.balances.at_location(location_id)
        if not holdings:
            return []
        names = await self._parts.names(workspace_id, {held.part_id for held in holdings})
        lots = [LocationLot(held, names.get(held.part_id)) for held in holdings]
        return sorted(
            lots,
            key=lambda lot: (lot.part_name is None, (lot.part_name or "").casefold()),
        )


class RebuildBalances:
    """`wiredex stock rebuild`: recompute every balance from the ledger, in one transaction.

    Streams the workspace's whole ledger in time order, folds it with the domain's
    `Balances.rebuilt_from`, and hands the result to `replace_all` — the projection is
    discarded and rewritten from the truth (requirement 5.2). One `commit`, so a rebuild is
    all-or-nothing per workspace; the caller (`stock rebuild`) opens one unit of work per
    workspace, so each bench is rebuilt under its own isolation.
    """

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId) -> None:
        async with self._unit_of_work(workspace_id) as work:
            movements: list[StockMovement] = [movement async for movement in work.ledger.all()]
            balances = Balances.rebuilt_from(movements)
            await work.balances.replace_all(balances.all())
            await work.commit()
