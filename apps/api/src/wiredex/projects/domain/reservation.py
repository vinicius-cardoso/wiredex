"""Choosing what a reservation takes (decision 2), over the stock a reserve locked.

Two decisions live here, both pure functions of what `BuildStock.available` locked, in
projects' own types so neither module imports the other's (decision 15): which named units a
reserve accepts (`check_named_units`), and what it takes (`Reservation.choose`). The use case
runs the checks and the shortage report first, so `choose` only ever meets stock that covers
the needs; anything else is a bug, raised as `ValueError`, not a refusal.

Decision 2, part by part:

- a part's named units come from their own lots, one piece each (requirement 3.2);
- the rest of its need comes from its lots ordered by the available stock the named units
  left, most first, ties by location code, each lot giving at most what it has left, so it
  draws on as few lots as the need allows (requirement 2.5);
- within a lot, its in-stock units that weren't named go first, in code order, one per piece,
  then loose pieces (requirements 3.1, 3.3);
- a lot's named units, chosen units and loose pieces make one `LotPick`, so one `RESERVE` per
  lot carries its whole share (requirement 14.3).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from wiredex.projects.domain.lifecycle import (
    RepeatedUnitError,
    TooManyUnitsError,
    Transition,
    UnitNotInStockError,
    UnitNotNeededError,
    UnknownUnitError,
)
from wiredex.projects.domain.shortage import PartFacts
from wiredex.projects.domain.values import LotId, PartId, UnitId


@dataclass(frozen=True, slots=True)
class ReservableLot:
    """One lot a reserve locked, in projects' terms."""

    lot_id: LotId
    part_id: PartId
    location_code: str
    available: int  # on hand less reserved, as the balance lock saw it


@dataclass(frozen=True, slots=True)
class StockUnit:
    """One unit a reserve locked: a part's in-stock unit, or a named one in any status."""

    unit_id: UnitId
    code: str
    part_id: PartId
    lot_id: LotId
    in_stock: bool  # False when reserved, built or retired


@dataclass(frozen=True, slots=True)
class ReservableStock:
    """`LockedStock` in projects' terms: what `BuildStock.available` locked for this reserve."""

    lots: tuple[ReservableLot, ...]  # the stocked parts' lots, in lot-id order
    units: tuple[StockUnit, ...]  # their in-stock units, in id order
    named: Mapping[UnitId, StockUnit]  # the named units the workspace holds, in any status
    now: datetime  # stamped after the balance lock: the reserve's time
    changed: bool  # the recount found an in-stock unit the unit lock missed

    def free(self) -> Mapping[PartId, int]:
        """Each part's available summed over its locked lots, the report's free stock (2.1)."""
        free: defaultdict[PartId, int] = defaultdict(int)
        for lot in self.lots:
            free[lot.part_id] += lot.available
        return dict(free)


@dataclass(frozen=True, slots=True)
class LotPick:
    """What a reservation takes from one lot: a quantity, and a unit per piece it can name."""

    lot_id: LotId
    quantity: int
    unit_ids: tuple[UnitId, ...]  # one per piece, up to quantity; the rest are loose pieces


@dataclass(frozen=True, slots=True)
class Reservation:
    """The lots a reserve takes from, one pick each, in lot-id order."""

    picks: tuple[LotPick, ...]

    @classmethod
    def choose(
        cls,
        needs: Mapping[PartId, int],
        stock: ReservableStock,
        named: Sequence[UnitId],
    ) -> Reservation:
        """Named units from their lots, the rest from the largest lots first (decision 2).

        `needs` is the stocked needs only, which the use case keeps from the BOM by the facts;
        it has run `check_named_units` and the shortage report first, so `named` is valid and
        the locked stock covers every need. A need `choose` can't cover is a bug, raised as
        `ValueError` (a `KeyError` or the assertion below), not a refusal.
        """
        named_ids = set(named)
        lots_by_part = _lots_by_part(stock)
        # A lot's units in stock, in code order, without the named ones: what a lot's chosen
        # pieces draw from after its own named units.
        free_units = _free_units_by_lot(stock, named_ids)
        picks = _Picks()  # built up per lot, so a lot named and drawn on ends one row (14.3)

        for part_id, need in needs.items():
            taken = _take_named(stock, named, part_id, picks)
            _take_from_lots(part_id, need - taken, lots_by_part, free_units, picks)

        return cls(
            tuple(
                LotPick(lot.lot_id, picks.quantity(lot.lot_id), picks.units(lot.lot_id))
                for lot in stock.lots
                if picks.quantity(lot.lot_id)
            )
        )


class _Picks:
    """The picks under construction, one growing quantity and unit list per lot, so the two
    accumulators travel together and a lot drawn on twice stays one row (requirement 14.3)."""

    def __init__(self) -> None:
        self._quantities: defaultdict[LotId, int] = defaultdict(int)
        self._unit_ids: defaultdict[LotId, list[UnitId]] = defaultdict(list)

    def add(self, lot_id: LotId, quantity: int, unit_ids: Sequence[UnitId] = ()) -> None:
        self._quantities[lot_id] += quantity
        self._unit_ids[lot_id].extend(unit_ids)

    def quantity(self, lot_id: LotId) -> int:
        return self._quantities[lot_id]

    def units(self, lot_id: LotId) -> tuple[UnitId, ...]:
        return tuple(self._unit_ids[lot_id])


def _lots_by_part(stock: ReservableStock) -> Mapping[PartId, list[ReservableLot]]:
    by_part: defaultdict[PartId, list[ReservableLot]] = defaultdict(list)
    for lot in stock.lots:
        by_part[lot.part_id].append(lot)
    return by_part


def _free_units_by_lot(
    stock: ReservableStock, named_ids: set[UnitId]
) -> Mapping[LotId, list[StockUnit]]:
    # In-stock units the owner didn't name, in code order, so `choose` and its property agree
    # on which unit each chosen piece takes (requirement 3.3).
    by_lot: defaultdict[LotId, list[StockUnit]] = defaultdict(list)
    for unit in sorted(stock.units, key=lambda unit: unit.code):
        if unit.in_stock and unit.unit_id not in named_ids:
            by_lot[unit.lot_id].append(unit)
    return by_lot


def _take_named(
    stock: ReservableStock, named: Sequence[UnitId], part_id: PartId, picks: _Picks
) -> int:
    """The part's named units, one piece each in their own lots, in the order the owner named
    them (requirement 3.2). Returns how many pieces they cover."""
    taken = 0
    for unit_id in named:
        unit = stock.named[unit_id]
        if unit.part_id == part_id:
            picks.add(unit.lot_id, 1, [unit_id])
            taken += 1
    return taken


def _take_from_lots(
    part_id: PartId,
    remaining: int,
    lots_by_part: Mapping[PartId, list[ReservableLot]],
    free_units: Mapping[LotId, list[StockUnit]],
    picks: _Picks,
) -> None:
    """The rest of the part's need from its lots, most available first, ties by location code
    (requirement 2.5). Within a lot its free units go first, in code order, then loose
    pieces (requirements 3.1, 3.3). Each lot gives at most the stock the named units left it."""
    if remaining <= 0:
        return
    ordered = sorted(
        lots_by_part[part_id],
        key=lambda lot: (-_left(lot, picks), lot.location_code),
    )
    for lot in ordered:
        if remaining <= 0:
            break
        take = min(remaining, _left(lot, picks))
        if take <= 0:
            continue
        # Each lot belongs to one part, so this call is the only one that draws chosen pieces
        # from it: its free units fill those pieces one for one, in code order, then loose
        # pieces (requirements 3.1, 3.3).
        chosen = free_units.get(lot.lot_id, [])[:take]
        picks.add(lot.lot_id, take, [unit.unit_id for unit in chosen])
        remaining -= take
    assert remaining == 0, "choose met a need the locked stock could not cover"  # noqa: S101


def _left(lot: ReservableLot, picks: _Picks) -> int:
    """A lot's available stock less what named units of it already took."""
    return lot.available - picks.quantity(lot.lot_id)


def check_named_units(
    needs: Mapping[PartId, int],
    facts: Mapping[PartId, PartFacts],  # noqa: ARG001  part of the port shape; needs is stocked-only
    named: Sequence[UnitId],
    stock: ReservableStock,
) -> None:
    """Refuse the first named unit that fails, in decision 12's order (requirements 3.4, 3.5).

    Five checks, each over the units in the order the owner named them; the first unit that
    fails a check is the one its refusal names, and no later check runs. `needs` is the stocked
    needs only, so a named unit of a part absent from it has no stocked need (a consumable's
    unit included, requirement 2.7); `facts` completes the port's shape the use case calls with,
    every fact `needs` already reflects.
    """
    _refuse_repeats(named)
    _refuse_unknown(named, stock)
    _refuse_not_needed(needs, named, stock)
    _refuse_too_many(needs, named, stock)
    _refuse_not_in_stock(named, stock)


def _refuse_repeats(named: Sequence[UnitId]) -> None:
    seen: set[UnitId] = set()
    for unit_id in named:
        if unit_id in seen:
            raise RepeatedUnitError(f"unit {unit_id} is named twice", Transition.RESERVE, unit_id)
        seen.add(unit_id)


def _refuse_unknown(named: Sequence[UnitId], stock: ReservableStock) -> None:
    for unit_id in named:
        if unit_id not in stock.named:
            # Row-level security hides another workspace's unit the same way (requirement 11.2).
            raise UnknownUnitError(
                f"unit {unit_id} is not in this workspace", Transition.RESERVE, unit_id
            )


def _refuse_not_needed(
    needs: Mapping[PartId, int], named: Sequence[UnitId], stock: ReservableStock
) -> None:
    for unit_id in named:
        unit = stock.named[unit_id]
        if unit.part_id not in needs:
            raise UnitNotNeededError(
                f"unit {unit.code} is of a part this build doesn't need",
                Transition.RESERVE,
                unit_id,
                unit_code=unit.code,
            )


def _refuse_too_many(
    needs: Mapping[PartId, int], named: Sequence[UnitId], stock: ReservableStock
) -> None:
    counted: defaultdict[PartId, int] = defaultdict(int)
    for unit_id in named:
        unit = stock.named[unit_id]
        counted[unit.part_id] += 1
        if counted[unit.part_id] > needs[unit.part_id]:
            raise TooManyUnitsError(
                f"more units of {unit.code}'s part are named than the build needs",
                Transition.RESERVE,
                unit_id,
                unit_code=unit.code,
            )


def _refuse_not_in_stock(named: Sequence[UnitId], stock: ReservableStock) -> None:
    # A lot can cover only so many named units before their pieces pass its available stock
    # (06's gap, seen while designing): count them per lot as they are named.
    taken: defaultdict[LotId, int] = defaultdict(int)
    available = {lot.lot_id: lot.available for lot in stock.lots}
    for unit_id in named:
        unit = stock.named[unit_id]
        taken[unit.lot_id] += 1
        if not unit.in_stock or taken[unit.lot_id] > available.get(unit.lot_id, 0):
            raise UnitNotInStockError(
                f"unit {unit.code} is not in stock",
                Transition.RESERVE,
                unit_id,
                unit_code=unit.code,
            )
