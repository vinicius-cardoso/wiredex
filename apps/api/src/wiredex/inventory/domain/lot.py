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

from wiredex.inventory.domain.errors import (
    NegativeStockError,
    ReservationError,
    ReservedStockError,
)
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
        """The next balance after a movement, each count moved by the movement's kind.

        `moves_on_hand` kinds (RECEIVE, ADJUST, MOVE, CONSUME, RETURN) move on_hand by the
        change; `moves_reserved` kinds (RESERVE, RELEASE, CONSUME) move reserved by it; CONSUME
        moves both, the other kinds leaving what they don't move as it was (requirements 2.6,
        7.3, 8.3).

        The floor holds for every on-hand kind: `NegativeStockError` if on_hand would drop
        below zero. When an on-hand movement would leave on_hand below what is reserved — a
        recount below the reserved count, a move of more than the available stock — the error
        is `ReservedStockError`, whose message says how many are reserved (requirements 7.1,
        7.2). Any other break of `0 <= reserved <= on_hand`, such as a RESERVE past on_hand or
        a RELEASE below zero, is a `ReservationError` (requirement 7.4).
        """
        on_hand = int(self.on_hand) + (movement.change if movement.kind.moves_on_hand else 0)
        reserved = int(self.reserved) + (movement.change if movement.kind.moves_reserved else 0)
        if on_hand < 0:
            raise NegativeStockError(
                f"a movement of {movement.change} would take on_hand to {on_hand}, below zero"
            )
        if reserved < 0:
            raise ReservationError(
                f"a movement of {movement.change} would take reserved to {reserved}, below zero"
            )
        if reserved > on_hand:
            # An on-hand movement dropping on_hand under an unchanged reservation is the hard
            # hold; a reserved movement pushing reserved past on_hand is a plain bounds break.
            if movement.kind.moves_on_hand and not movement.kind.moves_reserved:
                raise ReservedStockError(
                    f"on_hand can't fall to {on_hand}, below the {reserved} reserved for builds",
                    reserved,
                )
            raise ReservationError(
                f"reserved ({reserved}) can't exceed on_hand ({on_hand}) after the movement"
            )
        return StockBalance(
            lot_id=self.lot_id,
            on_hand=Quantity(on_hand),
            reserved=Quantity(reserved),
            version=self.version + 1,
        )

    @classmethod
    def opening(cls, lot_id: StockLotId) -> StockBalance:
        """The empty balance a lot starts from: zero on hand, zero reserved, version zero."""
        return cls(lot_id=lot_id, on_hand=Quantity(0), reserved=Quantity(0), version=0)
