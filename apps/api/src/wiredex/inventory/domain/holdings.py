"""What one revision holds of the stock, folded from its ledger rows (design decision 1).

There is no reservations table: a revision's reservation on a lot is the sum of its RESERVE,
RELEASE and CONSUME changes on that lot, and its consumption of a part is minus the sum of its
CONSUME and RETURN changes on the part's lots. `stock_movements.revision_id` has held that
"caused by" since 05, so the ledger already carries everything a second store would copy.

SQL only groups a revision's rows into `MovementSum`s, one per (lot, kind); `HeldStock.of`
does the fold, so it stays plain domain code a Hypothesis property can walk. It reads no
status: a draft or a dismantled revision holds nothing because its rows sum to zero
(requirements 8.5, 8.6).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from wiredex.inventory.domain.values import LocationId, MovementKind, PartId, StockLotId


@dataclass(frozen=True, slots=True)
class MovementSum:
    """One revision's changes of one kind on one lot, summed by the database.

    `change` keeps the ledger's sign: positive for RESERVE and RETURN, negative for RELEASE
    and CONSUME (requirement 8.2), so the fold adds the sums straight.
    """

    lot_id: StockLotId
    part_id: PartId
    location_id: LocationId
    location_code: str
    kind: MovementKind
    change: int


@dataclass(frozen=True, slots=True)
class LotHolding:
    """How many of a lot a revision reserves, with the lot's part and location for the read."""

    lot_id: StockLotId
    part_id: PartId
    location_id: LocationId
    location_code: str
    quantity: int


@dataclass(frozen=True, slots=True)
class PartHeld:
    """How much of one part a revision holds: reserved over the part's lots, and consumed by
    its build."""

    reserved: int
    consumed: int


@dataclass(frozen=True, slots=True)
class HeldStock:
    """What one revision holds: per lot what it reserves, per part what its build consumed.

    While reserved, `reserved` is the reservation per lot and `consumed` is empty; while built,
    `consumed` is what the build took per part and `reserved` is empty; a draft or dismantled
    revision holds neither, its rows summing to zero (requirement 8.6).
    """

    reserved: tuple[LotHolding, ...]
    consumed: Mapping[PartId, int]

    @classmethod
    def of(cls, sums: Iterable[MovementSum]) -> HeldStock:
        """Fold a revision's movement sums into what it holds.

        Per lot the reservation is RESERVE + RELEASE + CONSUME (the last two negative), so a
        lot fully released or fully consumed nets to zero. Per part the consumption is minus
        (CONSUME + RETURN): a build's CONSUME is negative and its later RETURN positive, so a
        dismantled part nets to zero. Zero holdings are dropped, so a draft or dismantled
        revision holds nothing (requirements 8.5, 8.6).
        """
        reserved_by_lot: dict[StockLotId, int] = defaultdict(int)
        consumed_by_part: dict[PartId, int] = defaultdict(int)
        lots: dict[StockLotId, MovementSum] = {}
        for entry in sums:
            if entry.kind.moves_reserved:
                # RESERVE positive, RELEASE and CONSUME negative: what the lot still reserves.
                reserved_by_lot[entry.lot_id] += entry.change
                lots.setdefault(entry.lot_id, entry)
            if entry.kind in (MovementKind.CONSUME, MovementKind.RETURN):
                # CONSUME negative then RETURN positive: minus their sum is what the build holds.
                consumed_by_part[entry.part_id] -= entry.change

        reserved = tuple(
            LotHolding(
                lot_id=lot_id,
                part_id=lots[lot_id].part_id,
                location_id=lots[lot_id].location_id,
                location_code=lots[lot_id].location_code,
                quantity=quantity,
            )
            for lot_id, quantity in reserved_by_lot.items()
            if quantity
        )
        consumed = {part_id: quantity for part_id, quantity in consumed_by_part.items() if quantity}
        return cls(reserved=reserved, consumed=consumed)

    def per_part(self) -> dict[PartId, PartHeld]:
        """What the revision holds of each part: its reservation summed over the part's lots,
        and what its build consumed. A part it holds none of is absent, so a draft or a
        dismantled revision answers nothing (10's requirement 10.4, 18's requirement 1.4)."""
        reserved_by_part: dict[PartId, int] = defaultdict(int)
        for holding in self.reserved:
            reserved_by_part[holding.part_id] += holding.quantity
        held = dict.fromkeys([*reserved_by_part, *self.consumed])
        return {
            part_id: PartHeld(reserved_by_part.get(part_id, 0), self.consumed.get(part_id, 0))
            for part_id in held
        }
