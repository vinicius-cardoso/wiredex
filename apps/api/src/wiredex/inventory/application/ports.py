"""What the inventory use cases need from the outside, as Protocols over domain types.

No repository method takes a workspace: the unit of work is built for one workspace and its
repositories only ever see that workspace's rows (ADR 0007, design §3). That is also why the
unit of work exposes them as read-only properties — a protocol attribute would have to match
exactly, so `SqlLocations` wouldn't count as `Locations`.

The command and result dataclasses live here too: frozen slotted dataclasses of domain types,
the shapes the use cases take in and hand back, next to the ports they travel through.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from wiredex.inventory.domain.ledger import StockMovement
from wiredex.inventory.domain.location import Location
from wiredex.inventory.domain.lot import StockBalance, StockLot
from wiredex.inventory.domain.unit import Unit
from wiredex.inventory.domain.values import (
    LocationId,
    LocationName,
    Mac,
    MovementReason,
    Note,
    PartId,
    Quantity,
    Serial,
    StockLotId,
    UnitId,
    WorkspaceId,
)
from wiredex.shared_kernel.application.ports import UnitOfWork


class ShortCodeKind(StrEnum):
    """Which counter a short code is drawn from: one per kind, per workspace.

    The value is what the `short_code_counters.kind` column stores. Locations are minted
    this release; units join from the next spec, sharing the same counter mechanism.
    """

    LOCATION = "location"
    UNIT = "unit"


class Locations(Protocol):
    async def add(self, location: Location) -> None: ...

    async def get(self, location_id: LocationId) -> Location | None: ...

    async def all(self) -> list[Location]:
        """Every location of the workspace, which is what the tree is built from (1.12)."""
        ...

    async def ancestors(self, location_id: LocationId) -> list[Location]:
        """The chain above the location, root first, in one round trip (requirement 10.1)."""
        ...

    async def children_of(self, location_id: LocationId) -> list[Location]: ...

    async def sibling_named(
        self, parent_id: LocationId | None, name: LocationName
    ) -> Location | None:
        """The location already using that name under that parent, two roots included.

        `parent_id=None` means among the roots, which the table spells `NULLS NOT DISTINCT`.
        """
        ...

    async def has_lots(self, location_id: LocationId) -> bool:
        """Whether any lot sits in the location, which blocks a delete (requirement 1.10)."""
        ...

    async def remove(self, location: Location) -> None: ...


class Lots(Protocol):
    async def get(self, lot_id: StockLotId) -> StockLot | None: ...

    async def for_part_at(self, part_id: PartId, location_id: LocationId) -> StockLot | None:
        """The lot of a (part, location) pair, or None before the first receive (3.1, 3.2)."""
        ...

    async def add(self, lot: StockLot) -> None: ...


class Ledger(Protocol):
    async def append(self, movement: StockMovement) -> None:
        """Add one row. Append-only: there is no update or delete path (ADR 0002, 4.10)."""
        ...

    async def movements_of(self, lot_id: StockLotId) -> list[StockMovement]: ...

    def all(self) -> AsyncIterator[StockMovement]:
        """Every movement of the workspace in time order, streamed for a rebuild (5.2)."""
        ...


class BalanceSheet(Protocol):
    async def get(self, lot_id: StockLotId) -> StockBalance | None:
        """The lot's balance, locked for the rest of the transaction.

        Two movements on one lot then take turns, and both effects count (5.5): the second
        reads the balance the first committed.
        """
        ...

    async def put(self, balance: StockBalance) -> None:
        """Write a balance whose `version` follows the stored one.

        Raises `ConcurrentStockError` when it doesn't, which rolls the movement back with it:
        a balance that silently missed its update would leave the ledger and the projection
        disagreeing.
        """
        ...

    async def totals_by_part(self, part_ids: Sequence[PartId]) -> dict[PartId, int]:
        """The total on_hand per part across its lots, one grouped query (7.1, 7.2)."""
        ...

    async def by_part(self, part_id: PartId) -> list[LotBalance]:
        """A part's on_hand broken down by location, each with its location (7.3)."""
        ...

    async def replace_all(self, balances: Iterable[StockBalance]) -> None:
        """Replace the whole projection with these, for `wiredex stock rebuild` (5.2)."""
        ...


class ShortCodes(Protocol):
    async def next(self, kind: ShortCodeKind) -> int:
        """Advance the workspace's counter for a kind inside the transaction, gap-free (2.1).

        Returns the next integer; the location use case formats it with
        `ShortCode.for_location`. Concurrent callers in one workspace are serialized, so a
        number is handed out once (requirement 2.2).
        """
        ...


class Units(Protocol):
    async def get(self, unit_id: UnitId) -> Unit | None: ...

    async def add(self, unit: Unit) -> None: ...

    async def of_part(self, part_id: PartId) -> list[Unit]:
        """The part's units, for its list on the part page (requirement 6.1)."""
        ...

    async def of_lot(self, lot_id: StockLotId) -> list[Unit]:
        """The units sitting in a lot, which is a location's units for that part (6.2)."""
        ...

    async def in_stock_at(self, lot_id: StockLotId) -> int:
        """How many `in_stock` units point at the lot, the count the invariant checks (9.1)."""
        ...

    async def search(self, term: str) -> list[Unit]:
        """Units whose code, serial or MAC contains the term, case-insensitive (6.3, 2.5)."""
        ...

    async def serial_taken(self, part_id: PartId, serial: Serial) -> bool:
        """Whether another unit of the part already holds the serial, folding case (5.1)."""
        ...

    async def mac_taken(self, mac: Mac) -> bool:
        """Whether another unit in the workspace already holds the MAC (requirement 5.2)."""
        ...

    async def remove(self, unit: Unit) -> None: ...


@dataclass(frozen=True, slots=True)
class PartStockInfo:
    """What inventory learns about a part through the `Parts` port, without seeing a Category.

    `exists` is false for a part the catalog doesn't know (a 404 receive); a part in a
    unit-tracked category answers `tracked_individually=True` (a 422 lot receive).
    """

    exists: bool
    tracked_individually: bool


class Parts(Protocol):
    async def describe(self, workspace_id: WorkspaceId, part_id: PartId) -> PartStockInfo:
        """Whether the part exists and how it is counted, in one call (6.1, 6.2, 6.3, 4.2)."""
        ...


class InventoryUnitOfWork(UnitOfWork, Protocol):
    async def clear(self) -> None:
        """Empty this workspace's inventory, for a demo bench being restored (ADR 0007, 8.6)."""
        ...

    # Read-only properties, not attributes: a protocol attribute would have to match
    # exactly, so `SqlLocations` wouldn't count as `Locations`.
    @property
    def locations(self) -> Locations: ...

    @property
    def lots(self) -> Lots: ...

    @property
    def ledger(self) -> Ledger: ...

    @property
    def balances(self) -> BalanceSheet: ...

    @property
    def short_codes(self) -> ShortCodes: ...


# --- Commands and results: the shapes the use cases take in and hand back -------------------


@dataclass(frozen=True, slots=True)
class NewLocation:
    """A location to create: a name, and the parent it hangs under, or None for a root."""

    name: LocationName
    parent_id: LocationId | None = None


@dataclass(frozen=True, slots=True)
class Receipt:
    """Receiving a quantity of a part into a location (requirement 4.1)."""

    part_id: PartId
    location_id: LocationId
    quantity: Quantity
    note: Note | None = None


@dataclass(frozen=True, slots=True)
class Adjustment:
    """Recounting a lot to an absolute counted quantity, with a reason (4.3, 4.4)."""

    part_id: PartId
    location_id: LocationId
    counted: Quantity
    reason: MovementReason
    note: Note | None = None


@dataclass(frozen=True, slots=True)
class Move:
    """Moving a quantity of a part from one location to another (requirement 4.5)."""

    part_id: PartId
    from_location_id: LocationId
    to_location_id: LocationId
    quantity: Quantity
    note: Note | None = None


@dataclass(frozen=True, slots=True)
class LocationNode:
    """A location in the tree with the two counts the list carries (requirement 1.12)."""

    location: Location
    child_count: int
    lot_count: int


@dataclass(frozen=True, slots=True)
class LotBalance:
    """One row of a part's per-location breakdown: where, and how much sits there (7.3)."""

    location: Location
    on_hand: Quantity


@dataclass(frozen=True, slots=True)
class PartStockView:
    """A part's total on_hand and its breakdown by location (requirements 7.3, 7.4)."""

    total: int
    breakdown: list[LotBalance]
