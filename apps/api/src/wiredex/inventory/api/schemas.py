"""What inventory takes and gives over HTTP, in primitives only.

No domain object reaches a field: the `from_*` classmethods do the converting, as catalog's
do. Movement responses carry the resulting balance so the web updates without a refetch — a
receive or adjust answers one balance, a move answers both lots' (design's HTTP API).
"""

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, Field

from wiredex.inventory.application.ports import (
    LocationNode,
    LotBalance,
    PartStockView,
)
from wiredex.inventory.application.units import UnitsReceived
from wiredex.inventory.domain.location import Location
from wiredex.inventory.domain.lot import StockBalance
from wiredex.inventory.domain.unit import Unit

# The reasons an adjust may carry, spelled out for the wire so the generated client gets a
# union it can switch on. A test keeps this in step with the `MovementReason` enum.
type MovementReasonName = Literal["recount", "damaged", "lost", "found", "correction"]

# A retire's reason is one of the two a lost or broken board gets; `damaged` is the default a
# body may leave out. Narrower than `MovementReasonName` on purpose: the other reasons belong
# to an adjust, not to retiring a unit (design's HTTP API).
type RetireReasonName = Literal["damaged", "lost"]

# A unit's status on the wire, the two v0.4.0 values (requirement 3.7).
type UnitStatusName = Literal["in_stock", "retired"]


class CreateLocationRequest(BaseModel):
    name: str
    # No parent makes it a root location (requirements 1.1, 1.2).
    parent_id: UUID | None = None


class UpdateLocationRequest(BaseModel):
    """A rename, a move, or both. What the body left out is left alone.

    `parent_id: null` is a move to the root, a different thing from not sending it, so the
    handler asks `moves()` rather than reading the value, as catalog's category patch does.
    """

    name: str | None = None
    parent_id: UUID | None = None

    def moves(self) -> bool:
        return "parent_id" in self.model_fields_set


class ReceiveRequest(BaseModel):
    """Receiving a positive quantity of a part into a location (requirement 4.1)."""

    part_id: UUID
    location_id: UUID
    quantity: int = Field(ge=1)
    note: str | None = None


class AdjustRequest(BaseModel):
    """Recounting a lot to an absolute counted quantity, with a reason (4.3, 4.4).

    `counted` is the absolute number the owner counted, not a delta: the use case works out
    the signed change and stores that.
    """

    part_id: UUID
    location_id: UUID
    counted: int = Field(ge=0)
    reason: MovementReasonName
    note: str | None = None


class MoveRequest(BaseModel):
    """Moving a positive quantity of a part from one location to another (requirement 4.5)."""

    part_id: UUID
    from_location_id: UUID
    to_location_id: UUID
    quantity: int = Field(ge=1)
    note: str | None = None


class LocationResponse(BaseModel):
    """A location on the wire, its short code shown so a bin reads as `WX-L-0007` (2.1)."""

    id: UUID
    parent_id: UUID | None
    code: str
    name: str
    created_at: datetime

    @classmethod
    def from_location(cls, location: Location) -> Self:
        return cls(
            id=location.id,
            parent_id=location.parent_id,
            code=str(location.code),
            name=location.name.value,
            created_at=location.created_at,
        )


class LocationNodeResponse(LocationResponse):
    """A location as the tree shows it, with the counts requirement 1.12 asks for."""

    child_count: int
    lot_count: int

    @classmethod
    def from_node(cls, node: LocationNode) -> Self:
        base = LocationResponse.from_location(node.location)
        return cls(**base.model_dump(), child_count=node.child_count, lot_count=node.lot_count)


class BalanceResponse(BaseModel):
    """The resulting balance a movement answers with, so the web updates in place.

    `available` is `on_hand - reserved`; in v0.4.0 `reserved` is always zero, so it equals
    `on_hand`, but the field is here from day one (design's HTTP API, requirement 3.4).
    """

    lot_id: UUID
    on_hand: int
    reserved: int
    available: int

    @classmethod
    def from_balance(cls, balance: StockBalance) -> Self:
        return cls(
            lot_id=balance.lot_id,
            on_hand=int(balance.on_hand),
            reserved=int(balance.reserved),
            available=int(balance.available),
        )


class MoveResponse(BaseModel):
    """Both lots' balances after a move: what left the source, and what the destination now
    holds (design's HTTP API)."""

    source: BalanceResponse
    destination: BalanceResponse

    @classmethod
    def from_balances(cls, source: StockBalance, destination: StockBalance) -> Self:
        return cls(
            source=BalanceResponse.from_balance(source),
            destination=BalanceResponse.from_balance(destination),
        )


class PartTotalResponse(BaseModel):
    """One part's total on_hand, for the batch the parts list asks for (requirements 7.1, 7.2)."""

    part_id: UUID
    on_hand: int


class LotBalanceResponse(BaseModel):
    """One row of a part's per-location breakdown: where, and how much sits there (7.3)."""

    location: LocationResponse
    on_hand: int

    @classmethod
    def from_lot_balance(cls, row: LotBalance) -> Self:
        return cls(
            location=LocationResponse.from_location(row.location),
            on_hand=int(row.on_hand),
        )


class PartStockResponse(BaseModel):
    """A part's total on_hand and its breakdown by location (requirements 7.3, 7.4).

    A part never received reports a total of zero and an empty breakdown, not a 404.
    """

    total: int
    breakdown: list[LotBalanceResponse]

    @classmethod
    def from_view(cls, view: PartStockView) -> Self:
        return cls(
            total=view.total,
            breakdown=[LotBalanceResponse.from_lot_balance(row) for row in view.breakdown],
        )


# --- Units --------------------------------------------------------------------------------


class NewUnitBody(BaseModel):
    """One unit in a receipt: an optional serial and MAC, either or both may be blank (5.5).

    The MAC is taken in any accepted spelling and canonicalized by the `Mac` value object;
    the router hands it over as typed so a malformed one is a 422 with the field named.
    """

    serial: str | None = None
    mac: str | None = None


class ReceiveUnitsRequest(BaseModel):
    """Receiving units of a unit-tracked part into a location (requirement 1.1).

    The `units` list's length is the quantity: one entry per unit, so N units are one
    `RECEIVE` of N on the (part, location) lot. At least one unit, since a receipt of nothing
    is nothing to do.
    """

    part_id: UUID
    location_id: UUID
    units: list[NewUnitBody] = Field(min_length=1)


class RelabelUnitRequest(BaseModel):
    """A unit's serial and MAC, both optional and both replaced by what the body carries.

    A field left `null` clears that label; the use case refuses a duplicate and commits
    nothing when neither changed (requirement 5.6).
    """

    serial: str | None = None
    mac: str | None = None


class MoveUnitRequest(BaseModel):
    """Moving one unit to a destination location (requirement 4.1)."""

    to_location_id: UUID


class RetireUnitRequest(BaseModel):
    """Retiring a unit, with the reason it left stock; `damaged` when the body omits it (3.1)."""

    reason: RetireReasonName = "damaged"


class UnitResponse(BaseModel):
    """A unit on the wire: its identity, its status, and where it sits (requirements 6.1, 8.3).

    The location is the unit's lot's location, resolved by the API; it is present for every
    unit (a unit always points at a lot in some location), but typed optional so a response
    never fails to serialize if a lot were ever missing. The MAC and serial are the canonical
    stored forms.
    """

    id: UUID
    part_id: UUID
    lot_id: UUID
    code: str
    serial: str | None
    mac: str | None
    status: UnitStatusName
    location: LocationResponse | None
    created_at: datetime

    @classmethod
    def of(cls, unit: Unit, location: Location | None) -> Self:
        return cls(
            id=unit.id,
            part_id=unit.part_id,
            lot_id=unit.lot_id,
            code=str(unit.code),
            serial=None if unit.serial is None else str(unit.serial),
            mac=None if unit.mac is None else str(unit.mac),
            status=unit.status.value,
            location=None if location is None else LocationResponse.from_location(location),
            created_at=unit.created_at,
        )


class ReceiveUnitsResponse(BaseModel):
    """A receipt's result: the units created (each with its minted code) and the lot's new
    balance, so the web shows the codes and updates the balance without a refetch (design's
    HTTP API)."""

    units: list[UnitResponse]
    balance: BalanceResponse

    @classmethod
    def of(cls, received: UnitsReceived, location: Location | None) -> Self:
        return cls(
            units=[UnitResponse.of(unit, location) for unit in received.units],
            balance=BalanceResponse.from_balance(received.balance),
        )
