"""The unit use cases: identity over stock the ledger already counts (design's decision 1).

`ReceiveUnits` is the first — and the mirror of the lot `ReceiveStock`. It writes the ordinary
lot + `RECEIVE` + balance, *and* creates N `Unit` rows pointing at that lot, in one
transaction, so a unit-tracked part counts through the same ledger as a lot-counted one and
the parts page's total query is unchanged. A lot's `on_hand`, for a unit-tracked part, equals
the number of its `in_stock` units at that location — the invariant property 1 guards. Its
`perform` is the same receipt without the commit, for a use case that receives units inside a
transaction it opened itself.

The command carries one `{serial?, mac?}` per unit, its length the quantity. The receive
mints one code per unit from the `unit` counter (consecutive, gap-free within the
transaction, property 4) and applies each unit's serial and MAC — refusing a duplicate serial
(per part, 409) or MAC (per workspace, 409) *before* writing anything, so a rejected receipt
creates nothing (requirement 1.7).

The unit of work these use cases speak exposes `units` alongside `lots`, `ledger`,
`balances` and `short_codes`: the shared `InventoryUnitOfWork` port carries it now that the
`SqlUnits` repository is bound (task 8), so these use cases type against that port directly.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from wiredex.inventory.application.movements import (
    MoveStock,
    _balance_of,
    _find_or_create_lot,
    _new_lot,
    _refuse_not_stocked,
)
from wiredex.inventory.application.ports import (
    InventoryUnitOfWork,
    Move,
    Parts,
    ShortCodeKind,
    Units,
)
from wiredex.inventory.domain.errors import (
    DuplicateMacError,
    DuplicateSerialError,
    InventoryError,
    PartNotFoundError,
    ReceiveAsLotError,
    SameLocationError,
    UnitNotFoundError,
    UnitNotRetiredError,
)
from wiredex.inventory.domain.ledger import StockMovement
from wiredex.inventory.domain.location import Location
from wiredex.inventory.domain.lot import StockBalance
from wiredex.inventory.domain.unit import Unit, UnitStatus
from wiredex.inventory.domain.values import (
    LocationId,
    Mac,
    MovementKind,
    MovementReason,
    PartId,
    Quantity,
    Serial,
    ShortCode,
    StockLotId,
    StockMovementId,
    UnitId,
    WorkspaceId,
)
from wiredex.shared_kernel.application.ports import Clock, IdGenerator

type UnitOfWorkFactory = Callable[[WorkspaceId], InventoryUnitOfWork]


@dataclass(frozen=True, slots=True)
class NewUnit:
    """One unit to create in a receipt: an optional serial and MAC, both may be blank (5.5)."""

    serial: Serial | None = None
    mac: Mac | None = None


@dataclass(frozen=True, slots=True)
class UnitReceipt:
    """Receiving `len(units)` units of a part into a location (requirement 1.1).

    The list's length is the quantity: one `RECEIVE` of N on the (part, location) lot, and N
    units created, each with the serial and MAC of its entry.
    """

    part_id: PartId
    location_id: LocationId
    units: tuple[NewUnit, ...]


@dataclass(frozen=True, slots=True)
class UnitsReceived:
    """A receipt's result: the created units and the lot's new balance, so the web needs no
    refetch (design's HTTP API note)."""

    units: tuple[Unit, ...]
    balance: StockBalance


class ReceiveUnits:
    """Receive N units of a unit-tracked part into a location, in one transaction (1.1, 1.2).

    The part is checked through the `Parts` port, never by importing catalog: a part the
    catalog doesn't know is a 404 (`PartNotFoundError`, 1.3), a consumable is a 422
    (`NotStockedError`, 09's 2.1) asked before tracking as the lot receive asks it, and a
    lot-counted part is a 422 (`ReceiveAsLotError`, 1.5) — the mirror of the lot receive's
    `ReceiveAsUnitsError`. Then
    the lot is found or created (1.2), one `RECEIVE` of `+N` is appended and the balance moved
    by it (the inventory-stock receive path), N codes are minted from the `unit` counter, and
    N units are created pointing at the lot. Every serial and MAC is validated for a duplicate
    *before* any write, so a rejected receipt creates nothing (1.7); the lot's `on_hand` ends
    equal to the number of its `in_stock` units (1.4, property 1).
    """

    def __init__(
        self, unit_of_work: UnitOfWorkFactory, parts: Parts, clock: Clock, ids: IdGenerator
    ) -> None:
        self._unit_of_work = unit_of_work
        self._parts = parts
        self._clock = clock
        self._ids = ids

    async def __call__(self, workspace_id: WorkspaceId, receipt: UnitReceipt) -> UnitsReceived:
        await _check_unit_tracked(self._parts, workspace_id, receipt.part_id)
        async with self._unit_of_work(workspace_id) as work:
            received = await self.perform(workspace_id, work, receipt)
            await work.commit()
            return received

    async def perform(
        self, workspace_id: WorkspaceId, work: InventoryUnitOfWork, receipt: UnitReceipt
    ) -> UnitsReceived:
        """The duplicate checks, the lot, the `RECEIVE`, the codes and the units inside an
        already-open transaction, the way `MoveStock.perform` runs inside `MoveUnit`.

        `ReceiveUnits` checks the part through `Parts`, wraps this in its own transaction and
        commits. Quick-add and import call it inside the transaction that may also define the
        part, having learned from their own catalog that it is unit-tracked: `Parts` reads in
        another transaction and can't see a part defined a moment earlier. So the caller checks
        the part is unit-tracked, and the caller commits. A duplicate is still refused before
        this receipt writes anything.
        """
        _reject_receipt_duplicates(receipt.units)
        await _reject_stored_duplicates(work.units, receipt.part_id, receipt.units)
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
            change=len(receipt.units),
            reason=None,
            note=None,
            move_group=None,
            revision_id=None,
            created_at=self._clock.now(),
        )
        await work.ledger.append(movement)
        balance = balance.apply(movement)
        await work.balances.put(balance)
        created: list[Unit] = []
        for entry in receipt.units:
            number = await work.short_codes.next(ShortCodeKind.UNIT)
            unit = Unit(
                id=UnitId(self._ids.new_id()),
                workspace_id=workspace_id,
                part_id=receipt.part_id,
                lot_id=lot.id,
                code=ShortCode.for_unit(number),
                serial=entry.serial,
                mac=entry.mac,
                status=UnitStatus.IN_STOCK,
                created_at=self._clock.now(),
            )
            await work.units.add(unit)
            created.append(unit)
        return UnitsReceived(units=tuple(created), balance=balance)


async def _check_unit_tracked(parts: Parts, workspace_id: WorkspaceId, part_id: PartId) -> None:
    """A part must exist and be unit-tracked before a unit receive (1.3, 1.5).

    The mirror of the lot receive's checks: a part the catalog doesn't know is a 404, a
    consumable a 422 `NotStockedError` whatever its tracking (09's 2.4), and a lot-counted part
    a 422 `ReceiveAsLotError` — it takes the loose lot receive.
    """
    info = await parts.describe(workspace_id, part_id)
    if not info.exists:
        raise PartNotFoundError("no such part in this workspace")
    _refuse_not_stocked(info)
    if not info.tracked_individually:
        raise ReceiveAsLotError("this part is counted in lots, not tracked as units")


def _reject_receipt_duplicates(units: tuple[NewUnit, ...]) -> None:
    """Refuse a receipt that repeats a serial or a MAC within itself, before any write.

    Two units in one receipt can't claim the same identity, just as two stored ones can't, so
    the whole receipt is rejected before a single row is written (requirements 5.1, 5.2)."""
    seen_serials: set[str] = set()
    seen_macs: set[str] = set()
    for entry in units:
        if entry.serial is not None:
            folded = entry.serial.fold()
            if folded in seen_serials:
                raise DuplicateSerialError(f"the serial {entry.serial} is repeated in the receipt")
            seen_serials.add(folded)
        if entry.mac is not None:
            canonical = str(entry.mac)
            if canonical in seen_macs:
                raise DuplicateMacError(f"the MAC {entry.mac} is repeated in the receipt")
            seen_macs.add(canonical)


async def _reject_stored_duplicates(
    units_repo: Units, part_id: PartId, units: tuple[NewUnit, ...]
) -> None:
    """Refuse a serial (per part) or MAC (per workspace) another unit already holds, before
    any write (5.1, 5.2). Kept separate so the whole receipt is validated first, then written."""
    for entry in units:
        if entry.serial is not None and await units_repo.serial_taken(part_id, entry.serial):
            raise DuplicateSerialError(
                f"another unit of this part already has serial {entry.serial}"
            )
        if entry.mac is not None and await units_repo.mac_taken(entry.mac):
            raise DuplicateMacError(f"another unit in this workspace already has MAC {entry.mac}")


class RelabelUnit:
    """Set a unit's serial and MAC, refusing a duplicate, committing only when changed (5.6).

    A unit the workspace doesn't know is a 404 (`UnitNotFoundError`). A duplicate serial (per
    part, 409) or MAC (per workspace, 409) another unit holds is refused before any write; the
    unit's own current serial or MAC never counts as a duplicate, so re-saving an unchanged
    label is allowed. `relabel` reports whether anything changed, so an unchanged relabel
    commits nothing (requirement 5.6).
    """

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(
        self,
        workspace_id: WorkspaceId,
        unit_id: UnitId,
        serial: Serial | None,
        mac: Mac | None,
    ) -> Unit:
        async with self._unit_of_work(workspace_id) as work:
            unit = await _load_unit(work.units, unit_id)
            await _reject_relabel_duplicates(work.units, unit, serial, mac)
            if unit.relabel(serial, mac):
                await work.commit()
            return unit


class RetireUnit:
    """`in_stock` → `retired`, writing a compensating `ADJUST -1` on the unit's lot (3.1).

    The lot's `on_hand` drops by one, so it stays equal to the number of its `in_stock` units
    (property 1). The reason is `damaged` by default, overridable to `lost`. A unit already
    retired is a no-op (requirement 3.6): no status write, no movement, no commit.
    """

    def __init__(self, unit_of_work: UnitOfWorkFactory, clock: Clock, ids: IdGenerator) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._ids = ids

    async def __call__(
        self,
        workspace_id: WorkspaceId,
        unit_id: UnitId,
        reason: MovementReason = MovementReason.DAMAGED,
    ) -> Unit:
        async with self._unit_of_work(workspace_id) as work:
            unit = await _load_unit(work.units, unit_id)
            if unit.retire():
                await _apply_adjust(work, self._adjust_row(workspace_id, unit.lot_id, -1, reason))
                await work.commit()
            return unit

    def _adjust_row(
        self, workspace_id: WorkspaceId, lot_id: StockLotId, change: int, reason: MovementReason
    ) -> StockMovement:
        return StockMovement(
            id=StockMovementId(self._ids.new_id()),
            workspace_id=workspace_id,
            lot_id=lot_id,
            kind=MovementKind.ADJUST,
            change=change,
            reason=reason,
            note=None,
            move_group=None,
            revision_id=None,
            created_at=self._clock.now(),
        )


class UnretireUnit:
    """`retired` → `in_stock`, writing a compensating `ADJUST +1` (reason `found`, 3.2).

    The lot's `on_hand` rises by one, back to counting the unit. A unit already `in_stock` is a
    no-op (requirement 3.6): no status write, no movement, no commit. Retiring then un-retiring
    returns the lot's `on_hand` to its starting value (property 3).
    """

    def __init__(self, unit_of_work: UnitOfWorkFactory, clock: Clock, ids: IdGenerator) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._ids = ids

    async def __call__(self, workspace_id: WorkspaceId, unit_id: UnitId) -> Unit:
        async with self._unit_of_work(workspace_id) as work:
            unit = await _load_unit(work.units, unit_id)
            if unit.unretire():
                movement = self._adjust_row(workspace_id, unit.lot_id, +1, MovementReason.FOUND)
                await _apply_adjust(work, movement)
                await work.commit()
            return unit

    def _adjust_row(
        self, workspace_id: WorkspaceId, lot_id: StockLotId, change: int, reason: MovementReason
    ) -> StockMovement:
        return StockMovement(
            id=StockMovementId(self._ids.new_id()),
            workspace_id=workspace_id,
            lot_id=lot_id,
            kind=MovementKind.ADJUST,
            change=change,
            reason=reason,
            note=None,
            move_group=None,
            revision_id=None,
            created_at=self._clock.now(),
        )


class MoveUnit:
    """Move one unit to another location, in one transaction (requirement 4.1).

    Delegates the stock effect to the inventory-stock two-row `MOVE` of quantity 1 (one
    `move_group`, source = the unit's current lot's location, destination = `to_location_id`),
    then repoints the unit's `lot_id` to the destination lot — all in the transaction the move
    wrote its balances in, so a unit's `lot_id` and the two lots' balances always agree
    (property 2). A retired unit can't move (422) and the same location is refused (422,
    `SameLocationError`, raised by the delegated move).
    """

    def __init__(
        self, unit_of_work: UnitOfWorkFactory, move_stock: MoveStock, clock: Clock, ids: IdGenerator
    ) -> None:
        self._unit_of_work = unit_of_work
        self._move_stock = move_stock
        self._clock = clock
        self._ids = ids

    async def __call__(
        self, workspace_id: WorkspaceId, unit_id: UnitId, to_location_id: LocationId
    ) -> Unit:
        async with self._unit_of_work(workspace_id) as work:
            unit = await _load_unit(work.units, unit_id)
            if unit.status is UnitStatus.RETIRED:
                raise InventoryError("a retired unit can't be moved; un-retire it first")
            lot = await work.lots.get(unit.lot_id)
            if lot is None:  # pragma: no cover - a unit always points at an existing lot
                raise UnitNotFoundError("the unit's lot is missing")
            if lot.location_id == to_location_id:
                raise SameLocationError("the unit is already in that location")
            move = Move(
                part_id=unit.part_id,
                from_location_id=lot.location_id,
                to_location_id=to_location_id,
                quantity=Quantity(1),
            )
            result = await self._move_stock.perform(workspace_id, work, move)
            unit.move_to(result.dest_lot_id)
            await work.commit()
            return unit


class DeleteUnit:
    """Delete a unit only if it is `retired`, leaving the ledger history intact (6.4, 6.5).

    An `in_stock` unit is refused with 409 (`UnitNotRetiredError`), so a hard delete never
    silently drops counted stock (design's decision 5). The ledger is append-only, so the
    unit's movements stay after the row is gone.
    """

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId, unit_id: UnitId) -> None:
        async with self._unit_of_work(workspace_id) as work:
            unit = await _load_unit(work.units, unit_id)
            if unit.status is not UnitStatus.RETIRED:
                raise UnitNotRetiredError("a unit must be retired before it can be deleted")
            await work.units.remove(unit)
            await work.commit()


class GetUnit:
    """One unit by id, or a 404 for one this workspace doesn't hold (requirements 7.2, 8.3).

    A read: no `commit`, scoped to the caller's workspace by the unit of work it opens, so
    another workspace's unit is nothing found — a 404, never a 403 (requirement 7.2).
    """

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId, unit_id: UnitId) -> Unit:
        async with self._unit_of_work(workspace_id) as work:
            return await _load_unit(work.units, unit_id)


class ListUnitsOfPart:
    """A part's units, for the list on its page (requirement 6.1).

    Each unit carries its code, serial, MAC, status and lot (its location); the API resolves
    the location for display. A read: no `commit`, and scoped to the caller's workspace by the
    unit of work it opens.
    """

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId, part_id: PartId) -> list[Unit]:
        async with self._unit_of_work(workspace_id) as work:
            return await work.units.of_part(part_id)


class ListUnitsOfLocation:
    """The units sitting in a location, across every lot there (requirement 6.2).

    A unit's location is its lot's location, so the repository joins units to their lots and
    keeps the ones at the location — never another location's, and never crossing workspaces.
    A read: no `commit`.
    """

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId, location_id: LocationId) -> list[Unit]:
        async with self._unit_of_work(workspace_id) as work:
            return await work.units.of_location(location_id)


class SearchUnits:
    """Units whose code, serial or MAC contains the term, case-insensitive (6.3, 2.5).

    The match is a case-insensitive substring over the three identity fields, so `WX-U-0042`,
    a serial and a MAC all find the same board (requirement 2.5). Each unit carries its part,
    lot (its location) and status, which the API turns into the search row (6.3). The term is
    trimmed; an empty term matches nothing rather than the whole workspace. A read: no
    `commit`, and scoped to the caller's workspace, so a search never crosses benches (7.3).
    """

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId, term: str) -> list[Unit]:
        needle = term.strip()
        if not needle:
            return []
        async with self._unit_of_work(workspace_id) as work:
            return await work.units.search(needle)


class LocateUnits:
    """The location each of these units sits in, so a listing can show *where* (6.1, 6.3).

    A unit's location is its lot's location; the read use cases hand back plain `Unit`s (they
    carry only `lot_id`), so the API resolves the location for display through this one read
    rather than importing a repository. It reads each distinct lot once and maps every unit to
    its lot's location; a unit whose lot or location has gone (it can't, `lot_id` is a
    RESTRICT FK) is simply absent from the map. A read: no `commit`, scoped to the workspace.
    """

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(
        self, workspace_id: WorkspaceId, units: Sequence[Unit]
    ) -> dict[UnitId, Location]:
        if not units:
            return {}
        async with self._unit_of_work(workspace_id) as work:
            locations = await self._locations_by_lot(work, units)
        located: dict[UnitId, Location] = {}
        for unit in units:
            location = locations.get(unit.lot_id)
            if location is not None:
                located[unit.id] = location
        return located

    async def _locations_by_lot(
        self, work: InventoryUnitOfWork, units: Sequence[Unit]
    ) -> dict[StockLotId, Location]:
        by_lot: dict[StockLotId, Location] = {}
        for lot_id in {unit.lot_id for unit in units}:
            lot = await work.lots.get(lot_id)
            if lot is None:  # pragma: no cover - a unit always points at an existing lot
                continue
            location = await work.locations.get(lot.location_id)
            if location is not None:
                by_lot[lot_id] = location
        return by_lot


async def _load_unit(units_repo: Units, unit_id: UnitId) -> Unit:
    """The unit in this workspace, or a 404 (`UnitNotFoundError`, requirement 7.2)."""
    unit = await units_repo.get(unit_id)
    if unit is None:
        raise UnitNotFoundError("no such unit in this workspace")
    return unit


async def _reject_relabel_duplicates(
    units_repo: Units, unit: Unit, serial: Serial | None, mac: Mac | None
) -> None:
    """Refuse a serial (per part) or MAC (per workspace) another unit holds, before any write.

    The unit's own current label never counts against it, so only a *changed* serial or MAC is
    checked (requirement 5.6): re-saving the same value, or clearing one, is always allowed.
    """
    if (
        serial is not None
        and (unit.serial is None or unit.serial.fold() != serial.fold())
        and await units_repo.serial_taken(unit.part_id, serial)
    ):
        raise DuplicateSerialError(f"another unit of this part already has serial {serial}")
    if mac is not None and unit.mac != mac and await units_repo.mac_taken(mac):
        raise DuplicateMacError(f"another unit in this workspace already has MAC {mac}")


async def _apply_adjust(work: InventoryUnitOfWork, movement: StockMovement) -> None:
    """Append one compensating `ADJUST` on its lot and move that lot's balance by it.

    The signed delta is stored, so "the sum of a lot's movements equals its on_hand" stays
    true for the retire/un-retire adjustments as for every other kind (movements' property 5).
    """
    balance = await _balance_of(work, movement.lot_id)
    await work.ledger.append(movement)
    await work.balances.put(balance.apply(movement))
