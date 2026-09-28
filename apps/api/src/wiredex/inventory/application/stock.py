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

from wiredex.inventory.application.ports import (
    InventoryUnitOfWork,
    LotBalance,
    PartStockView,
)
from wiredex.inventory.domain.ledger import Balances, StockMovement
from wiredex.inventory.domain.values import PartId, WorkspaceId

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
    """A part's total on_hand and its breakdown by location (requirements 7.3, 7.4).

    The total is the breakdown summed, so the two never disagree: a part in three drawers
    reports the three rows and their sum in one read. A part no lot has ever held reads as a
    total of zero and an empty breakdown — the honest answer, not a 404 (requirement 7.4).
    """

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId, part_id: PartId) -> PartStockView:
        async with self._unit_of_work(workspace_id) as work:
            breakdown: list[LotBalance] = await work.balances.by_part(part_id)
        total = sum(int(row.on_hand) for row in breakdown)
        return PartStockView(total=total, breakdown=breakdown)


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
