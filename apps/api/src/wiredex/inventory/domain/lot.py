"""A stock lot — the thin identity of "this part, in this location" — and its balance.

A lot's count never lives on the lot. It lives in a `StockBalance`, the projection of the
lot's ledger, and the ledger is the truth (ADR 0002). `StockBalance.apply` is the one place a
movement changes a count, so the floor and the reserved guard hold in a single spot the
property tests can pin down.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from wiredex.inventory.domain.errors import NegativeStockError, ReservationError
from wiredex.inventory.domain.values import (
    LocationId,
    PartId,
    Quantity,
    StockLotId,
    WorkspaceId,
)

if TYPE_CHECKING:
    from wiredex.inventory.domain.ledger import StockMovement


@dataclass(eq=False)
class StockLot:
    """The pairing of one part with one location, unique per workspace.

    Created the first time a part is received into a location and never deleted in v0.4.0 —
    a lot at zero is normal. It carries no short code: only locations and units do (design's
    use cases). `(workspace_id, part_id, location_id)` is unique.
    """

    id: StockLotId
    workspace_id: WorkspaceId
    part_id: PartId
    location_id: LocationId
    created_at: datetime


@dataclass(frozen=True, slots=True)
class StockBalance:
    """The projection of a lot's ledger: how much is on hand, reserved and available.

    Frozen, because `apply` returns a **new** balance rather than mutating this one: a
    movement produces the next balance, it doesn't edit the last. `version` is optimistic
    locking's column (ADR 0002); the use case retries a stale write.
    """

    lot_id: StockLotId
    on_hand: Quantity
    reserved: Quantity
    version: int

    @property
    def available(self) -> Quantity:
        """What can be taken: on_hand minus reserved (requirement 3.4). In v0.4.0 reserved is
        always zero, so this equals on_hand; the subtraction is written for v0.5.0 anyway."""
        return Quantity(int(self.on_hand) - int(self.reserved))

    def apply(self, movement: StockMovement) -> StockBalance:
        """The next balance after a movement, with on_hand moved by the signed change.

        Raises `NegativeStockError` if on_hand would drop below zero — the floor holds for
        *every* kind, ADJUST included (requirement 3.6) — and `ReservationError` if the
        result would break `0 <= reserved <= on_hand` (requirement 3.7). The reserved guard
        is unreachable in v0.4.0, since no movement touches reserved, but it is guarded and
        property-tested so v0.5.0 inherits it proven.
        """
        moved = int(self.on_hand) + movement.change
        if moved < 0:
            raise NegativeStockError(
                f"a movement of {movement.change} would take on_hand to {moved}, below zero"
            )
        if int(self.reserved) > moved:
            raise ReservationError(
                f"reserved ({self.reserved}) can't exceed on_hand ({moved}) after the movement"
            )
        return StockBalance(
            lot_id=self.lot_id,
            on_hand=Quantity(moved),
            reserved=self.reserved,
            version=self.version + 1,
        )

    @classmethod
    def opening(cls, lot_id: StockLotId) -> StockBalance:
        """The empty balance a lot starts from: zero on hand, zero reserved, version zero."""
        return cls(lot_id=lot_id, on_hand=Quantity(0), reserved=Quantity(0), version=0)
