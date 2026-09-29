"""A revision's stock, inside a caller's transaction (design decision 8).

`RevisionStock` is inventory's half of a build transition. It reserves, releases, consumes and
returns a revision's stock over an `InventoryRepositories` — the repositories on a session the
projects unit of work opened and set the workspace on — and it never commits: the projects
unit of work commits the whole transition, so the status, the movements, the balances and the
units land together (requirement 1.3), and a refusal anywhere rolls them all back (1.4).

It speaks inventory's own ids and types; `InventoryBuildStock` (task 12) translates to and
from projects' words. The four writes each stamp the time after the balance lock and hand it
back, so the use case moves the revision's last change to the instant the balances changed
(design decision 15): the reserve's time rides in `LockedStock.now`, the other three return
it.

The lock order is decision 10's, in every path: units by id, then balances by lot id, every
lock read `FOR UPDATE` with `populate_existing`. A cancel, a build and a dismantle read no
catalog and no status; each follows what the ledger says the revision holds, folded by
`HeldStock.of`, whatever the category flags say now (decision 16, requirement 5.3).
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from wiredex.inventory.application.ports import InventoryRepositories, LockedLot, RevisionUnitRow
from wiredex.inventory.domain.errors import LocationNotFoundError
from wiredex.inventory.domain.holdings import HeldStock
from wiredex.inventory.domain.ledger import StockMovement
from wiredex.inventory.domain.lot import StockBalance, StockLot
from wiredex.inventory.domain.unit import Unit, UnitStatus
from wiredex.inventory.domain.values import (
    LocationId,
    MovementKind,
    PartId,
    RevisionId,
    StockLotId,
    StockMovementId,
    UnitId,
    WorkspaceId,
)
from wiredex.shared_kernel.application.ports import Clock, IdGenerator

type _UnitMove = Callable[[Unit], None]


@dataclass(frozen=True, slots=True)
class LockedStock:
    """What `available` locked for a reserve, kept for its `reserve` in the same transaction.

    `lots` are the stocked parts' lots with their balances and location codes, in lot-id
    order; `units` are those parts' in-stock units, in id order; `named` are the named units
    the workspace holds, in any status. `now` is stamped after the balance lock — the reserve's
    time — and `changed` says the recount after the balance lock found an in-stock unit the
    unit lock hadn't seen, a `ReceiveUnits` committed between the two locks (decision 12).
    """

    lots: tuple[LockedLot, ...]
    units: tuple[Unit, ...]
    named: Mapping[UnitId, Unit]
    now: datetime
    changed: bool


@dataclass(frozen=True, slots=True)
class LotTake:
    """What a reservation takes from one lot: a quantity, and a unit per piece it can name.

    One `LotTake` per lot the reservation draws on, so one `RESERVE` carries the lot's whole
    share (requirement 14.3); `unit_ids` names one in-stock unit per piece it takes, up to the
    quantity, the rest loose pieces (requirements 3.1 to 3.3).
    """

    lot_id: StockLotId
    quantity: int
    unit_ids: tuple[UnitId, ...]


@dataclass(frozen=True, slots=True)
class PartHolding:
    """One revision holding a part: how many it reserves and how many its build consumed."""

    revision_id: RevisionId
    reserved: int
    consumed: int


class RevisionStock:
    """Reserve, release, consume and return a revision's stock, never committing.

    Built on the repositories the caller's transaction owns (`InventoryRepositories`), plus the
    clock and id source inventory's other use cases take. Every method leaves the `commit()` to
    the caller (decision 8).
    """

    def __init__(
        self,
        work: InventoryRepositories,
        workspace_id: WorkspaceId,
        clock: Clock,
        ids: IdGenerator,
    ) -> None:
        self._work = work
        self._workspace_id = workspace_id
        self._clock = clock
        self._ids = ids

    async def available(
        self, part_ids: Collection[PartId], named: Collection[UnitId]
    ) -> LockedStock:
        """Lock the parts' in-stock units and the named ones, then their lots; stamp; recount.

        Units are locked before balances (06's order, so no writer waits on another in a
        circle), and the named units — which may be in any status — are locked too, so a named
        unit not in stock is caught by the caller's `check_named_units`. The clock is read
        after the balance lock, so the ledger's order is the order the balances changed. Then
        the in-stock units in the locked lots are recounted: a `ReceiveUnits` committed between
        the unit lock and the balance lock leaves a piece whose unit the unit lock never saw,
        and `changed` says so, which the caller refuses as `stock_changed` (decision 12).
        """
        wanted_units = sorted({*named, *(await self._in_stock_unit_ids(part_ids))})
        locked_units = await self._work.units.lock(wanted_units)
        by_id = {unit.id: unit for unit in locked_units}
        in_stock = tuple(
            unit
            for unit in locked_units
            if unit.part_id in part_ids and unit.status is UnitStatus.IN_STOCK
        )
        named_units = {unit_id: by_id[unit_id] for unit_id in named if unit_id in by_id}

        lots = tuple(await self._work.balances.lock_by_part(sorted(part_ids)))
        now = self._clock.now()
        changed = await self._recount_changed(lots, in_stock)
        return LockedStock(lots=lots, units=in_stock, named=named_units, now=now, changed=changed)

    async def reserve(
        self,
        stock: LockedStock,
        revision_id: RevisionId,
        takes: Sequence[LotTake],
    ) -> None:
        """One `RESERVE` per lot taken, its balance applied and put, its named units reserved.

        Runs against what `available` locked in this transaction, so the balances it moves are
        the ones the reserve saw (requirement 2.8). Each take's quantity raises its lot's
        reserved and leaves on hand as it was (requirement 2.6); each named unit goes from in
        stock to reserved, linked to the revision (requirement 3.1). The caller commits.
        """
        by_lot = {locked.lot.id: locked for locked in stock.lots}
        units = {unit.id: unit for unit in stock.units}
        for take in takes:
            locked = by_lot[take.lot_id]
            await self._write(
                locked.lot, MovementKind.RESERVE, take.quantity, revision_id, now=stock.now
            )
            for unit_id in take.unit_ids:
                units[unit_id].reserve_for(revision_id)

    async def release(self, revision_id: RevisionId) -> datetime:
        """One `RELEASE` per lot of the whole reservation, the units back in stock (4.1, 3.7)."""
        return await self._unwind(revision_id, MovementKind.RELEASE, _release_unit)

    async def consume(self, revision_id: RevisionId) -> datetime:
        """One `CONSUME` per lot of the whole reservation, the units built (5.1, 3.6)."""
        return await self._unwind(revision_id, MovementKind.CONSUME, _build_unit)

    async def return_to(self, revision_id: RevisionId, location_id: LocationId) -> datetime:
        """One `RETURN` per consumed part into its lot at the location, the units in stock there.

        The location is checked first, so its refusal comes before any lock or write
        (requirement 6.1); `InventoryBuildStock` turns the not-found into `unknown_location`.
        Each consumed part's return lot is found at the location or created; its balance and the
        revision's in-use units are locked, then one `RETURN` of the whole consumption per part
        raises on hand and the units move into the return lot in stock (requirements 6.2, 3.7).
        """
        location = await self._work.locations.get(location_id)
        if location is None:
            raise LocationNotFoundError("no such location in this workspace")
        held = await self._holdings(revision_id)
        return_lots = await self._return_lots(location_id, held.consumed)
        units = await self._locked_revision_units(revision_id)
        # Lock the return lots' balances in lot-id order (decision 10); `_write` reads each
        # afresh, so this call is the lock, not the read.
        await self._work.balances.lock(sorted(lot.id for lot in return_lots.values()))
        now = self._clock.now()
        for part_id, quantity in held.consumed.items():
            lot = return_lots[part_id]
            await self._write(lot, MovementKind.RETURN, quantity, revision_id, now=now)
            for unit in units:
                if unit.part_id == part_id:
                    unit.return_to(lot.id)
        return now

    async def holdings(self, revision_id: RevisionId) -> HeldStock:
        """What the revision holds, folded from its sums in one query (requirement 8.5)."""
        return await self._holdings(revision_id)

    async def holdings_of_part(self, part_id: PartId) -> list[PartHolding]:
        """Each revision holding some of the part, folded the same way (requirement 10.4)."""
        by_revision = await self._work.ledger.sums_of_part(part_id)
        holdings: list[PartHolding] = []
        for revision_id, sums in by_revision.items():
            held = HeldStock.of(sums)
            reserved = sum(
                holding.quantity for holding in held.reserved if holding.part_id == part_id
            )
            consumed = held.consumed.get(part_id, 0)
            if reserved or consumed:
                holdings.append(PartHolding(revision_id, reserved, consumed))
        return holdings

    async def units_of(self, revision_id: RevisionId) -> list[RevisionUnitRow]:
        """The units reserved for or built into the revision, in one query (requirement 3.11)."""
        return await self._work.units.of_revision(revision_id)

    async def _unwind(
        self,
        revision_id: RevisionId,
        kind: MovementKind,
        move_unit: _UnitMove,
    ) -> datetime:
        """Release or consume: one row per lot of the whole reservation, its units moved.

        Both follow the ledger, not a status: `HeldStock.of` gives what the revision reserves
        per lot, its units are locked by id and those lots' balances by lot id, the time is
        stamped after the balance lock, and each lot gets one row of the whole quantity
        reserved there (requirements 4.1, 5.1). A `CONSUME` lowers both on hand and reserved; a
        `RELEASE` lowers only reserved (requirement 8.3).
        """
        held = await self._holdings(revision_id)
        units = await self._locked_revision_units(revision_id)
        lot_ids = [holding.lot_id for holding in held.reserved]
        balances = await self._work.balances.lock(sorted(lot_ids))
        by_lot = {locked.lot.id: locked for locked in balances}
        now = self._clock.now()
        for holding in held.reserved:
            lot = by_lot[holding.lot_id].lot
            await self._write(lot, kind, -holding.quantity, revision_id, now=now)
        for unit in units:
            move_unit(unit)
        return now

    async def _write(
        self,
        lot: StockLot,
        kind: MovementKind,
        change: int,
        revision_id: RevisionId,
        *,
        now: datetime,
    ) -> None:
        """Append one movement and move its lot's balance by it, both in the caller's
        transaction. The balance is read afresh here rather than reused, so a lot touched more
        than once in one transition folds each change onto the last."""
        balance = await self._balance_of(lot.id)
        movement = StockMovement(
            id=StockMovementId(self._ids.new_id()),
            workspace_id=self._workspace_id,
            lot_id=lot.id,
            kind=kind,
            change=change,
            reason=None,
            note=None,
            move_group=None,
            revision_id=revision_id,
            created_at=now,
        )
        await self._work.ledger.append(movement)
        await self._work.balances.put(balance.apply(movement))

    async def _holdings(self, revision_id: RevisionId) -> HeldStock:
        return HeldStock.of(await self._work.ledger.sums_of_revision(revision_id))

    async def _locked_revision_units(self, revision_id: RevisionId) -> list[Unit]:
        """The revision's held units, locked by id in id order (decision 10)."""
        rows = await self._work.units.of_revision(revision_id)
        return await self._work.units.lock(sorted(row.unit.id for row in rows))

    async def _in_stock_unit_ids(self, part_ids: Collection[PartId]) -> set[UnitId]:
        units = await self._work.units.in_stock_of_parts(sorted(part_ids))
        return {unit.id for unit in units}

    async def _return_lots(
        self,
        location_id: LocationId,
        consumed: Mapping[PartId, int],
    ) -> dict[PartId, StockLot]:
        """Each consumed part's lot at the location, the missing ones created (requirement 6.2)."""
        existing = await self._work.lots.at(location_id, sorted(consumed))
        lots: dict[PartId, StockLot] = {}
        for part_id in consumed:
            lot = existing.get(part_id)
            if lot is None:
                lot = StockLot(
                    id=StockLotId(self._ids.new_id()),
                    workspace_id=self._workspace_id,
                    part_id=part_id,
                    location_id=location_id,
                    created_at=self._clock.now(),
                )
                await self._work.lots.add(lot)
            lots[part_id] = lot
        return lots

    async def _balance_of(self, lot_id: StockLotId) -> StockBalance:
        balance = await self._work.balances.get(lot_id)
        return balance if balance is not None else StockBalance.opening(lot_id)

    async def _recount_changed(self, lots: Sequence[LockedLot], in_stock: Sequence[Unit]) -> bool:
        """Whether the balance lock counts an in-stock piece whose unit the unit lock missed.

        For each locked lot whose stock came in as units, its available stock should equal the
        in-stock units the unit lock saw in it. If the balance's available is higher, a
        `ReceiveUnits` committed between the two locks, and the reserve is refused as
        `stock_changed` (decision 12). A lot with no units — a loose-lot part — is left out:
        `in_stock_seen` is zero for it and its available stock isn't unit-backed, so it never
        trips the check.
        """
        seen: dict[StockLotId, int] = {}
        for unit in in_stock:
            seen[unit.lot_id] = seen.get(unit.lot_id, 0) + 1
        for locked in lots:
            in_stock_seen = seen.get(locked.lot.id, 0)
            if in_stock_seen == 0:
                continue
            reserved_units = await self._work.units.of_lot_reserved(locked.lot.id)
            # For a unit-backed lot on hand is its in-stock plus reserved units; a mismatch
            # against what we locked means a unit landed between the locks (requirement 3.9).
            if int(locked.balance.on_hand) != in_stock_seen + reserved_units:
                return True
        return False


def _release_unit(unit: Unit) -> None:
    """A cancel frees a reserved unit back to in stock (requirement 3.7)."""
    unit.release()


def _build_unit(unit: Unit) -> None:
    """A build marks a reserved unit in use, its revision link kept (requirement 3.6)."""
    unit.build()
