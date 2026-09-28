"""The three movement use cases this release records: receive, adjust and move.

Each is one class with one `async __call__`, and each is one transaction (AGENTS.md): the
ledger row (or rows) and the balance it moves are written together, so a committed movement
never lacks its balance effect (requirement 5.4). The commands they take — `Receipt`,
`Adjustment`, `Move` — live in `ports.py` alongside the ports they travel through (task 5).
`ReceiveStock` and `MoveStock` also offer `perform`: the same writes without the commit, for
a use case that composes them inside a transaction it opened itself.

Stock lives in an append-only ledger with a balance projection folded from it (ADR 0002).
`RECEIVE` adds a positive change; `ADJUST` takes an absolute counted quantity and stores the
signed delta, so "the sum of a lot's movements equals its on_hand" stays one uniform property
across every kind (property 5); `MOVE` writes two rows sharing one move group — a withdrawal
and an equal deposit — so a move relocates stock without inventing or losing any (property 4).
"""

from collections.abc import Callable
from dataclasses import dataclass

from wiredex.inventory.application.ports import (
    Adjustment,
    InventoryUnitOfWork,
    Move,
    Parts,
    PartStockInfo,
    Receipt,
)
from wiredex.inventory.domain.errors import (
    InsufficientStockError,
    NotStockedError,
    PartNotFoundError,
    ReceiveAsUnitsError,
    SameLocationError,
)
from wiredex.inventory.domain.ledger import MovementGroup, StockMovement
from wiredex.inventory.domain.lot import StockBalance, StockLot
from wiredex.inventory.domain.values import (
    LocationId,
    MoveGroupId,
    MovementKind,
    Note,
    PartId,
    StockLotId,
    StockMovementId,
    WorkspaceId,
)
from wiredex.shared_kernel.application.ports import Clock, IdGenerator

type UnitOfWorkFactory = Callable[[WorkspaceId], InventoryUnitOfWork]


class ReceiveStock:
    """Receive a quantity of a part into a location, appending one `RECEIVE` (requirement 4.1).

    The part is checked through the `Parts` port, never by importing catalog: a part the
    catalog doesn't know is a 404 (`PartNotFoundError`, 4.2), a consumable is a 422
    (`NotStockedError`, 09's 2.1), and a part its category tracks as individual units is a 422
    (`ReceiveAsUnitsError`, 6.3) — that part is received as units by the next spec, not as a
    loose lot count. The consumable is asked first, so a part resolving both flags is refused
    as not stocked (09's 2.4). Otherwise the lot is found or created (3.1,
    3.2), a `RECEIVE` of `+quantity` is appended, the balance is moved by it, and both are
    committed together.
    """

    def __init__(
        self, unit_of_work: UnitOfWorkFactory, parts: Parts, clock: Clock, ids: IdGenerator
    ) -> None:
        self._unit_of_work = unit_of_work
        self._parts = parts
        self._clock = clock
        self._ids = ids

    async def __call__(self, workspace_id: WorkspaceId, receipt: Receipt) -> StockBalance:
        info = await _check_exists(self._parts, workspace_id, receipt.part_id)
        _refuse_not_stocked(info)
        _refuse_unit_tracked(info)
        async with self._unit_of_work(workspace_id) as work:
            balance = await self.perform(workspace_id, work, receipt)
            await work.commit()
            return balance

    async def perform(
        self, workspace_id: WorkspaceId, work: InventoryUnitOfWork, receipt: Receipt
    ) -> StockBalance:
        """The lot, the `RECEIVE` and the balance inside an already-open transaction.

        `ReceiveStock` checks the part through `Parts`, wraps this in its own transaction and
        commits. Quick-add and import call it inside the transaction that may also define the
        part: they learn how the part is counted from their own catalog, in that transaction,
        because `Parts` reads in another one and can't see a part defined a moment earlier.
        So the caller checks the part is lot-counted, and the caller commits.
        """
        lot = await _find_or_create_lot(
            work,
            receipt.part_id,
            receipt.location_id,
            lambda: _new_lot(
                workspace_id, receipt.part_id, receipt.location_id, self._clock, self._ids
            ),
        )
        balance = await _balance_of(work, lot.id)
        movement = StockMovement(
            id=StockMovementId(self._ids.new_id()),
            workspace_id=workspace_id,
            lot_id=lot.id,
            kind=MovementKind.RECEIVE,
            change=int(receipt.quantity),
            reason=None,
            note=receipt.note,
            move_group=None,
            revision_id=None,
            created_at=self._clock.now(),
        )
        await work.ledger.append(movement)
        balance = balance.apply(movement)
        await work.balances.put(balance)
        return balance


class AdjustStock:
    """Recount a lot to an absolute counted quantity, appending one `ADJUST` (requirement 4.3).

    The input is the *absolute* number the owner counted, not a delta. The use case reads the
    lot's current `on_hand`, computes `change = counted - on_hand`, and stores that signed
    delta with the movement's reason (4.4). Storing the delta rather than the absolute number
    keeps "the sum of a lot's movements equals its on_hand" true for `ADJUST` as for every
    other kind (property 5). A part the catalog tracks as units is refused, as a receive is.
    A consumable is recounted only where it already has a lot: a recount elsewhere would
    create stock from nothing, which is a receipt by another name (09's 2.2).
    """

    def __init__(
        self, unit_of_work: UnitOfWorkFactory, parts: Parts, clock: Clock, ids: IdGenerator
    ) -> None:
        self._unit_of_work = unit_of_work
        self._parts = parts
        self._clock = clock
        self._ids = ids

    async def __call__(self, workspace_id: WorkspaceId, adjustment: Adjustment) -> StockBalance:
        info = await _check_lot_counted(self._parts, workspace_id, adjustment.part_id)
        async with self._unit_of_work(workspace_id) as work:
            # Asked inside the transaction, before anything is written. A lot at zero is still
            # a lot: recounting a drawer the part was kept in is recounting held stock.
            if info.not_stocked and (
                await work.lots.for_part_at(adjustment.part_id, adjustment.location_id) is None
            ):
                _refuse_not_stocked(info)
            lot = await _find_or_create_lot(
                work,
                adjustment.part_id,
                adjustment.location_id,
                lambda: _new_lot(
                    workspace_id,
                    adjustment.part_id,
                    adjustment.location_id,
                    self._clock,
                    self._ids,
                ),
            )
            balance = await _balance_of(work, lot.id)
            change = int(adjustment.counted) - int(balance.on_hand)
            movement = StockMovement(
                id=StockMovementId(self._ids.new_id()),
                workspace_id=workspace_id,
                lot_id=lot.id,
                kind=MovementKind.ADJUST,
                change=change,
                reason=adjustment.reason,
                note=adjustment.note,
                move_group=None,
                revision_id=None,
                created_at=self._clock.now(),
            )
            await work.ledger.append(movement)
            balance = balance.apply(movement)
            await work.balances.put(balance)
            await work.commit()
            return balance


@dataclass(frozen=True, slots=True)
class MoveResult:
    """The lots and balances a two-row MOVE touched, so a caller can repoint on the destination.

    `MoveUnit` (units spec) reads `dest_lot_id` to point the moved unit at its new lot, in the
    same transaction that wrote these balances.
    """

    source_lot_id: StockLotId
    dest_lot_id: StockLotId
    source_balance: StockBalance
    dest_balance: StockBalance


class MoveStock:
    """Move a quantity of a part between two locations, in one transaction (requirement 4.5).

    Two ledger rows share one `MoveGroupId`: `-quantity` on the source lot and `+quantity` on
    the destination, so the workspace's total for that part is unchanged, only its
    distribution (property 4). The source and destination must differ (`SameLocationError`,
    422, requirement 4.8); the source lot must hold at least `quantity` (`InsufficientStockError`,
    409, requirement 4.7); the destination lot is created if absent (requirement 4.9). One
    transaction means a failure on either side writes neither row. A part the catalog tracks
    as units is refused: its units would stay behind in the source lot, so it moves one unit
    at a time through `MoveUnit`, which calls `perform` directly.
    """

    def __init__(
        self, unit_of_work: UnitOfWorkFactory, parts: Parts, clock: Clock, ids: IdGenerator
    ) -> None:
        self._unit_of_work = unit_of_work
        self._parts = parts
        self._clock = clock
        self._ids = ids

    async def __call__(
        self, workspace_id: WorkspaceId, move: Move
    ) -> tuple[StockBalance, StockBalance]:
        if move.from_location_id == move.to_location_id:
            raise SameLocationError("a move needs a source and a destination that differ")
        await _check_lot_counted(self._parts, workspace_id, move.part_id)
        async with self._unit_of_work(workspace_id) as work:
            result = await self.perform(workspace_id, work, move)
            await work.commit()
            return result.source_balance, result.dest_balance

    async def perform(
        self, workspace_id: WorkspaceId, work: InventoryUnitOfWork, move: Move
    ) -> MoveResult:
        """The two-row MOVE inside an already-open transaction, so another use case can reuse it.

        `MoveStock` wraps it in its own transaction and commits; `MoveUnit` (units spec) calls
        it inside the transaction that also repoints the unit, so a unit's `lot_id` and the two
        lots' balances always move together (design's decision 4). The caller commits.
        """
        source = await work.lots.for_part_at(move.part_id, move.from_location_id)
        if source is None:
            raise InsufficientStockError("the source holds none of this part")
        dest = await _find_or_create_lot(
            work,
            move.part_id,
            move.to_location_id,
            lambda: _new_lot(
                workspace_id, move.part_id, move.to_location_id, self._clock, self._ids
            ),
        )
        # Both balances locked in one order (by lot id), so two opposite moves at the same
        # time wait for each other instead of each holding the lot the other needs.
        locked = {
            lot_id: await _balance_of(work, lot_id) for lot_id in sorted((source.id, dest.id))
        }
        source_balance, dest_balance = locked[source.id], locked[dest.id]
        quantity = int(move.quantity)
        if int(source_balance.on_hand) < quantity:
            raise InsufficientStockError("the source holds less than the quantity being moved")
        group_id = MoveGroupId(self._ids.new_id())
        out_of = self._move_row(workspace_id, source.id, -quantity, group_id, move.note)
        into = self._move_row(workspace_id, dest.id, quantity, group_id, move.note)
        # Grouping proves conservation before anything is written: the pair sums to zero.
        MovementGroup(group_id, out_of, into)
        await work.ledger.append(out_of)
        await work.ledger.append(into)
        source_balance = source_balance.apply(out_of)
        dest_balance = dest_balance.apply(into)
        await work.balances.put(source_balance)
        await work.balances.put(dest_balance)
        return MoveResult(
            source_lot_id=source.id,
            dest_lot_id=dest.id,
            source_balance=source_balance,
            dest_balance=dest_balance,
        )

    def _move_row(
        self,
        workspace_id: WorkspaceId,
        lot_id: StockLotId,
        change: int,
        group_id: MoveGroupId,
        note: Note | None,
    ) -> StockMovement:
        return StockMovement(
            id=StockMovementId(self._ids.new_id()),
            workspace_id=workspace_id,
            lot_id=lot_id,
            kind=MovementKind.MOVE,
            change=change,
            reason=None,
            note=note,
            move_group=group_id,
            revision_id=None,
            created_at=self._clock.now(),
        )


async def _check_lot_counted(
    parts: Parts, workspace_id: WorkspaceId, part_id: PartId
) -> PartStockInfo:
    """A part must exist and be lot-counted before a lot adjust or move (4.2, 6.3)."""
    info = await _check_exists(parts, workspace_id, part_id)
    _refuse_unit_tracked(info)
    return info


async def _check_exists(parts: Parts, workspace_id: WorkspaceId, part_id: PartId) -> PartStockInfo:
    """What the catalog says of the part, or a 404 for a part it doesn't know (4.2)."""
    info = await parts.describe(workspace_id, part_id)
    if not info.exists:
        raise PartNotFoundError("no such part in this workspace")
    return info


def _refuse_not_stocked(info: PartStockInfo) -> None:
    """A consumable is never received: its category resolves not stocked (09's 2.1). A unit
    receipt asks the same question first, with the same sentence."""
    if info.not_stocked:
        raise NotStockedError("this part's category isn't stocked, so none of it is received")


def _refuse_unit_tracked(info: PartStockInfo) -> None:
    if info.tracked_individually:
        raise ReceiveAsUnitsError("this part is tracked as units, not counted as a lot")


async def _find_or_create_lot(
    work: InventoryUnitOfWork,
    part_id: PartId,
    location_id: LocationId,
    make_lot: Callable[[], StockLot],
) -> StockLot:
    """The lot of a (part, location) pair, created on first touch (requirements 3.1, 3.2).

    `make_lot` mints the new lot from the caller's clock and ids, so this helper stays free of
    both and small enough to read.
    """
    lot = await work.lots.for_part_at(part_id, location_id)
    if lot is not None:
        return lot
    lot = make_lot()
    await work.lots.add(lot)
    return lot


def _new_lot(
    workspace_id: WorkspaceId,
    part_id: PartId,
    location_id: LocationId,
    clock: Clock,
    ids: IdGenerator,
) -> StockLot:
    """A fresh lot for a (part, location) pair, from the use case's clock and ids."""
    return StockLot(
        id=StockLotId(ids.new_id()),
        workspace_id=workspace_id,
        part_id=part_id,
        location_id=location_id,
        created_at=clock.now(),
    )


async def _balance_of(work: InventoryUnitOfWork, lot_id: StockLotId) -> StockBalance:
    """A lot's balance, or its opening balance when nothing has touched it yet (7.4)."""
    balance = await work.balances.get(lot_id)
    return balance if balance is not None else StockBalance.opening(lot_id)
