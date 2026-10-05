"""What the inventory use cases need from the outside, as Protocols over domain types.

No repository method takes a workspace: the unit of work is built for one workspace and its
repositories only ever see that workspace's rows (ADR 0007, design §3). That is also why the
unit of work exposes them as read-only properties — a protocol attribute would have to match
exactly, so `SqlLocations` wouldn't count as `Locations`.

The command and result dataclasses live here too: frozen slotted dataclasses of domain types,
the shapes the use cases take in and hand back, next to the ports they travel through.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from wiredex.inventory.domain.holdings import MovementSum
from wiredex.inventory.domain.intake import CellProblem, KnownPart, PartDraft
from wiredex.inventory.domain.ledger import StockMovement
from wiredex.inventory.domain.location import Location
from wiredex.inventory.domain.lot import StockBalance, StockLot
from wiredex.inventory.domain.unit import Unit, UnitStatus
from wiredex.inventory.domain.values import (
    LocationId,
    LocationName,
    Mac,
    MovementReason,
    Note,
    PartId,
    Quantity,
    RevisionId,
    Serial,
    StockLotId,
    UnitId,
    WorkspaceId,
)
from wiredex.shared_kernel.application.ports import UnitOfWork
from wiredex.shared_kernel.domain.paging import PageRequest
from wiredex.shared_kernel.domain.trash import TrashedSlice


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

    async def find(self, text: str, limit: int) -> list[Location]:
        """The locations whose name or code contains the text, case aside, the ones whose name
        starts with it first, then by name, at most `limit`, in one query (19-command-palette,
        decision 1)."""
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

    async def lot_counts(self) -> Mapping[LocationId, int]:
        """How many lots sit in each location that holds any, in one round trip: the tree's
        counts (requirement 1.12). A location holding none is absent."""
        ...

    async def remove(self, location: Location) -> None: ...


class Lots(Protocol):
    async def get(self, lot_id: StockLotId) -> StockLot | None: ...

    async def for_part_at(self, part_id: PartId, location_id: LocationId) -> StockLot | None:
        """The lot of a (part, location) pair, or None before the first receive (3.1, 3.2)."""
        ...

    async def at(
        self, location_id: LocationId, part_ids: Sequence[PartId]
    ) -> dict[PartId, StockLot]:
        """The return lots: each part's lot at the location, for the parts that have one.

        A dismantle returns each consumed part into its lot at the chosen location, so this
        finds the lots that already exist there in one query; the ones that don't the use case
        creates (requirement 6.2). A part with no lot at the location is absent from the map.
        """
        ...

    async def add(self, lot: StockLot) -> None: ...

    async def locations_of(self, lot_ids: Collection[StockLotId]) -> dict[StockLotId, Location]:
        """The location each of these lots sits in, in one read whatever their number: what a
        list of units shows beside each (the boards list). A lot the workspace doesn't hold is
        absent."""
        ...


class Ledger(Protocol):
    async def append(self, movement: StockMovement) -> None:
        """Add one row. Append-only: there is no update or delete path (ADR 0002, 4.10)."""
        ...

    async def movements_of(self, lot_id: StockLotId) -> list[StockMovement]: ...

    def all(self) -> AsyncIterator[StockMovement]:
        """Every movement of the workspace in time order, streamed for a rebuild (5.2)."""
        ...

    async def sums_of_revision(self, revision_id: RevisionId) -> list[MovementSum]:
        """A revision's changes grouped by lot, part, location and kind, in one query (8.5).

        Over the partial index `(workspace_id, revision_id) WHERE revision_id IS NOT NULL`,
        so a revision's holdings are folded from a handful of rows whatever the ledger's size
        (design's decision 1). `HeldStock.of` does the fold; this only groups.
        """
        ...

    async def sums_of_part(self, part_id: PartId) -> dict[RevisionId, list[MovementSum]]:
        """Each revision holding some of the part, its sums grouped the same way (10.4).

        One part's lots' rows, grouped by revision, lot, part, location and kind, so
        `ListPartHoldings` folds each revision's holding of the part in one query whatever the
        number of revisions (requirement 10.6).
        """
        ...

    async def sums_of_holdings(self) -> dict[RevisionId, list[MovementSum]]:
        """Every revision's sums, grouped the same way, in one query (18-dashboard, decision 1).

        All the workspace's rows naming a revision, whatever their part, so the dashboard folds
        the parts tied up in builds in one read whatever the number of revisions, parts and
        lots (18's requirement 6.1).
        """
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

    async def available_by_part(self, part_ids: Sequence[PartId]) -> dict[PartId, int]:
        """The total available per part across its lots, the same grouped query summing
        `available` (09's requirements 6.2, 12.3). A part no lot holds is absent."""
        ...

    async def by_part(self, part_id: PartId) -> list[LotBalance]:
        """A part's on_hand broken down by location, each with its location (7.3)."""
        ...

    async def at_location(self, location_id: LocationId) -> list[LotHolding]:
        """The lots sitting in the location, each with its part, on hand and reserved, in one
        read: what the location holds, as its page lists it. A lot with no balance yet holds
        nothing."""
        ...

    async def stocked_parts(self) -> set[PartId]:
        """Every part with stock on hand, its lots summed, its in-stock units included, in one
        grouped read: what the parts list's stock filter narrows by."""
        ...

    async def lock(self, lot_ids: Sequence[StockLotId]) -> list[LockedLot]:
        """Lock these lots' balances FOR UPDATE, in lot-id order, with each lot's part and its
        location code, in one query (design's decision 10).

        A reserve locks the stocked parts' lots; a cancel, build or dismantle locks the lots a
        revision holds. Both take them in lot-id order and with `populate_existing`, so a row
        already in the session is refreshed with what the lock saw. A lot with no balance row
        yet — a fresh return lot — comes back with its opening balance so the caller can write
        the first one. Ordering is the caller's: it sorts the ids before calling.
        """
        ...

    async def lock_by_part(self, part_ids: Sequence[PartId]) -> list[LockedLot]:
        """Lock every lot of these parts FOR UPDATE, in lot-id order, with part and code (2.8).

        What a reserve locks: the stocked parts' lots, so the second of two reserves on one
        part sees what the first left (requirement 2.8). Same `populate_existing` and lot-id
        order as `lock`.
        """
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
    """The workspace's units. Every read but the two uniqueness checks and the trash's own
    leaves a unit in the trash out, as a unit that doesn't exist (16-soft-delete-and-trash,
    decision 2)."""

    async def get(self, unit_id: UnitId) -> Unit | None:
        """The live unit, its row locked until the transaction ends, or None. A request queued
        behind a move to the trash wakes up to nothing (16's decision 3)."""
        ...

    async def of_ids(self, unit_ids: Collection[UnitId]) -> list[Unit]:
        """The listed units the workspace holds, in one read and unlocked, by code; any other is
        absent. What another module's directory reads (15-flash-log decision 8)."""
        ...

    async def add(self, unit: Unit) -> None: ...

    async def of_part(self, part_id: PartId) -> list[Unit]:
        """The part's units, for its list on the part page (requirement 6.1)."""
        ...

    async def of_lot(self, lot_id: StockLotId) -> list[Unit]:
        """The units sitting in a lot, which is a location's units for that part (6.2)."""
        ...

    async def of_location(self, location_id: LocationId) -> list[Unit]:
        """The units sitting in a location, across every lot there (requirement 6.2).

        A unit's location is its lot's location, so this joins units to their lots and keeps
        the ones at the location — the query the units table's `(workspace_id, lot_id)` index
        and the lots' `location_id` support. A unit in use answers no location (it sits on a
        board, not in the drawer), so this leaves in-use units out (design's decision 5).
        """
        ...

    async def in_stock_at(self, lot_id: StockLotId) -> int:
        """How many `in_stock` units point at the lot, the count the invariant checks (9.1)."""
        ...

    async def of_revision(self, revision_id: RevisionId) -> list[RevisionUnitRow]:
        """The units reserved for or built into the revision, joined to their lots and
        locations, in one query (requirement 3.11).

        A held unit answers its lot's location code while reserved and none while in use — it
        sits on a board, not in a drawer (design's decision 5). Ordered by code, the order the
        holdings read in.
        """
        ...

    async def lock(self, unit_ids: Sequence[UnitId]) -> list[Unit]:
        """Lock these units FOR UPDATE, in id order, with `populate_existing` (decision 10).

        The reserve locks the parts' in-stock units and the named ones; a cancel, build or
        dismantle locks a revision's held units. Units are locked before balances, the order
        06's writers already take, so no two writers wait on each other in a circle. Ordering
        is the caller's: it sorts the ids first. Another workspace's id, or one the workspace
        doesn't hold, is simply absent from the result.
        """
        ...

    async def in_stock_of_parts(self, part_ids: Sequence[PartId]) -> list[Unit]:
        """The in-stock units of these parts, locked FOR UPDATE in id order (decision 10).

        What a reserve locks for its automatic choice, and the recount after the balance lock
        counts against: a `ReceiveUnits` committed between the two locks would leave an
        in-stock unit this lock never saw (design decision 12). `populate_existing` refreshes
        any row already in the session.
        """
        ...

    async def of_lot_reserved(self, lot_id: StockLotId) -> int:
        """How many `reserved` units point at the lot, the other half of the invariant (3.9)."""
        ...

    async def count(self, query: UnitQuery) -> int:
        """How many units `search` keeps for the query, in one read: the boards list's total."""
        ...

    async def search(self, query: UnitQuery, page: PageRequest) -> list[Unit]:
        """The page of the units the query keeps, newest first, the id breaking ties, in one
        read: those whose code, serial or MAC contains its term, case aside (6.3, 2.5), in its
        status and of its part when it names them. A blank term keeps every unit."""
        ...

    async def part_counts(self) -> dict[PartId, int]:
        """How many live units each part has, retired ones included, in one grouped read: the
        parts the boards list's part filter offers. A part with no unit is absent."""
        ...

    async def find(self, text: str, limit: int) -> list[Unit]:
        """`search` at most `limit` at a time, the codes starting with the text first, then by
        code, in one query over the trigram indexes (19-command-palette, decision 1)."""
        ...

    async def serial_taken(self, part_id: PartId, serial: Serial) -> bool:
        """Whether another unit of the part already holds the serial, folding case (5.1), a
        unit in the trash included: it keeps its serial there (16's decision 5)."""
        ...

    async def mac_taken(self, mac: Mac) -> bool:
        """Whether another unit in the workspace already holds the MAC (requirement 5.2), a
        unit in the trash included."""
        ...

    async def remove(self, unit: Unit) -> None: ...

    async def trashed(
        self, count: int, text: str | None, part_ids: frozenset[PartId]
    ) -> TrashedSlice[Unit]:
        """The newest `count` units in the trash whose code holds the text, case aside, or whose
        part is one of `part_ids`, the id breaking ties, and how many match in all, in one query
        (16's decision 9). No text narrows nothing, and `part_ids` then counts for nothing; `%`
        and `_` in the text are characters, not wildcards."""
        ...

    async def in_trash(self, unit_id: UnitId) -> Unit | None:
        """The unit if it is in the trash, its row locked and read fresh, or None (16's
        decision 10)."""
        ...

    async def empty_trash(self) -> int:
        """Every unit in the trash deleted for good, in one statement; how many went. Their
        movements stay, as the ledger keeps them."""
        ...


@dataclass(frozen=True, slots=True)
class PartStockInfo:
    """What inventory learns about a part through the `Parts` port, without seeing a Category.

    `exists` is false for a part the catalog doesn't know (a 404 receive); a part in a
    unit-tracked category answers `tracked_individually=True` (a 422 lot receive), and one in
    a category resolving not stocked answers `not_stocked=True` (a 422 receipt of either kind,
    09's decision 4). The two flags resolve independently, so both can be true.
    """

    exists: bool
    tracked_individually: bool
    not_stocked: bool


class Parts(Protocol):
    async def describe(self, workspace_id: WorkspaceId, part_id: PartId) -> PartStockInfo:
        """Whether the part exists and how it is counted, in one call (6.1, 6.2, 6.3, 4.2)."""
        ...

    async def names(
        self, workspace_id: WorkspaceId, part_ids: Collection[PartId]
    ) -> Mapping[PartId, str]:
        """The name of each of these parts, in one read whatever their number, for a list that
        shows the part beside each row. A part the catalog doesn't hold, or one in the trash,
        is absent."""
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

    @property
    def units(self) -> Units: ...


class InventoryRepositories(Protocol):
    """The inventory repositories with no commit, for a caller that owns the transaction.

    `RevisionStock` reserves, releases, consumes and returns a revision's stock on a session
    another module's unit of work opened and set the workspace on (design decision 8), so it
    needs the repositories without a `commit()` of its own — the projects unit of work commits
    the whole transition. It is the mirror of 07's `CatalogRepositories`: the same repositories
    the `InventoryUnitOfWork` exposes, as read-only properties so a concrete `SqlLots` counts
    as `Lots`, but without the transaction machinery.
    """

    @property
    def lots(self) -> Lots: ...

    @property
    def ledger(self) -> Ledger: ...

    @property
    def balances(self) -> BalanceSheet: ...

    @property
    def units(self) -> Units: ...

    @property
    def locations(self) -> Locations: ...


# --- Intake: the catalog's half, in inventory's words ----------------------------------------


@dataclass(frozen=True, slots=True)
class PartReview:
    """What the catalog says about a draft: its problems, or the part it names.

    A draft naming a stored part has no problems, since a row isn't judged on the cells it
    doesn't use (requirement 5.1); a new part's problems are every one of them (1.5).
    """

    problems: tuple[CellProblem, ...]  # row left None; the planner stamps it
    existing: KnownPart | None  # the part already holding this manufacturer and part number
    category_id: UUID | None  # None while the category is a problem
    category_path: str | None  # its full path, for the preview
    tracked_individually: bool | None  # resolved along the chain; None with the category
    identity: str | None  # manufacturer and part number folded, what a sheet matches on
    not_stocked: bool | None  # resolved along the chain too; None with the category


class PartCatalog(Protocol):
    """The part half of an intake, answered inside the caller's transaction (design
    decision 2): a property of `IntakeUnitOfWork`, not a constructor argument like `Parts`,
    because a part it defines has to be written, and seen, in the same transaction as its
    stock."""

    async def review(self, draft: PartDraft) -> PartReview:
        """Reads only: what the draft would do, and what stands in its way."""
        ...

    async def define(self, draft: PartDraft, pinout_from: PartId | None = None) -> KnownPart:
        """Define the part in the caller's transaction, with a copy of `pinout_from`'s pinout
        when it is given; the caller commits.

        Refuses with inventory's own errors (`IntakeRefusedError`, `PartAlreadyDefinedError`,
        `PartNotFoundError` for a pinout source the workspace doesn't hold), since inventory
        can't catch catalog's.
        """
        ...


class IntakeUnitOfWork(InventoryUnitOfWork, Protocol):
    """Inventory's unit of work plus the catalog, bound to the same transaction by the
    composition root, so one `commit()` keeps a part and its stock together, and leaving
    without it keeps neither (requirement 12.1)."""

    @property
    def catalog(self) -> PartCatalog: ...


type IntakeUnitOfWorkFactory = Callable[[WorkspaceId], IntakeUnitOfWork]


# --- Commands and results: the shapes the use cases take in and hand back -------------------


@dataclass(frozen=True, slots=True)
class UnitQuery:
    """What the boards list narrows the workspace's units by, each only when given: a term the
    code, serial or MAC contains, a status, and the part they are of."""

    term: str = ""
    status: UnitStatus | None = None
    part_id: PartId | None = None


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
    """One row of a part's per-location breakdown: where, and how much sits there (7.3).

    On hand, reserved and available, so a stock view shows what is set aside for builds beside
    what is on the shelf; available is on hand less reserved, never stored (requirement 10.3).
    """

    location: Location
    on_hand: Quantity
    reserved: Quantity

    @property
    def available(self) -> Quantity:
        """On hand less reserved: what can still be taken (requirement 10.3)."""
        return Quantity(int(self.on_hand) - int(self.reserved))


@dataclass(frozen=True, slots=True)
class LotHolding:
    """One lot a location holds: its part, on hand and reserved, available derived as in
    `LotBalance`."""

    lot_id: StockLotId
    part_id: PartId
    on_hand: Quantity
    reserved: Quantity

    @property
    def available(self) -> Quantity:
        """On hand less reserved: what can still be taken."""
        return Quantity(int(self.on_hand) - int(self.reserved))


@dataclass(frozen=True, slots=True)
class LocationLot:
    """A lot a location holds, named: its part's name as the catalog holds it, or None for a
    part the catalog no longer holds."""

    holding: LotHolding
    part_name: str | None


@dataclass(frozen=True, slots=True)
class PartStockView:
    """A part's totals and its breakdown by location (requirements 7.3, 7.4, 10.3).

    The totals are the breakdown summed count by count, so the total and its rows never
    disagree; available is the total on hand less the total reserved.
    """

    total: int
    reserved: int
    breakdown: list[LotBalance]

    @property
    def available(self) -> int:
        """The total on hand less the total reserved (requirement 10.3)."""
        return self.total - self.reserved


@dataclass(frozen=True, slots=True)
class LockedLot:
    """A lot locked for a transition: the lot, its balance, and its location code.

    The balance's `available` (on hand less reserved) is what a reserve's shortage report and
    its choice read; the location code orders a part's lots when their available stock ties.
    A lot with no balance row yet — a fresh return lot — carries its opening balance, so the
    caller writes the first `put` (decision 10).
    """

    lot: StockLot
    balance: StockBalance
    location_code: str


@dataclass(frozen=True, slots=True)
class RevisionUnitRow:
    """One unit a revision holds, with its lot's location code, or none while in use (3.11)."""

    unit: Unit
    location_code: str | None
