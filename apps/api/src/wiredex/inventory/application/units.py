"""The unit use cases: identity over stock the ledger already counts (design's decision 1).

`ReceiveUnits` is the first — and the mirror of the lot `ReceiveStock`. It writes the ordinary
lot + `RECEIVE` + balance, *and* creates N `Unit` rows pointing at that lot, in one
transaction, so a unit-tracked part counts through the same ledger as a lot-counted one and
the parts page's total query is unchanged. A lot's `on_hand`, for a unit-tracked part, equals
the number of its `in_stock` units at that location — the invariant property 1 guards.

The command carries one `{serial?, mac?}` per unit, its length the quantity. The receive
mints one code per unit from the `unit` counter (consecutive, gap-free within the
transaction, property 4) and applies each unit's serial and MAC — refusing a duplicate serial
(per part, 409) or MAC (per workspace, 409) *before* writing anything, so a rejected receipt
creates nothing (requirement 1.7).

The unit of work these use cases speak also exposes `units`; the concrete
`SqlInventoryUnitOfWork` binds that repository from task 8, so this module declares the shape
it needs locally rather than widening the shared `InventoryUnitOfWork` port before its SQL
side exists.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from wiredex.inventory.application.movements import (
    _balance_of,
    _find_or_create_lot,
    _new_lot,
)
from wiredex.inventory.application.ports import (
    InventoryUnitOfWork,
    Parts,
    ShortCodeKind,
    Units,
)
from wiredex.inventory.domain.errors import (
    DuplicateMacError,
    DuplicateSerialError,
    PartNotFoundError,
    ReceiveAsLotError,
)
from wiredex.inventory.domain.ledger import StockMovement
from wiredex.inventory.domain.lot import StockBalance
from wiredex.inventory.domain.unit import Unit, UnitStatus
from wiredex.inventory.domain.values import (
    LocationId,
    Mac,
    MovementKind,
    PartId,
    Serial,
    ShortCode,
    StockMovementId,
    UnitId,
    WorkspaceId,
)
from wiredex.shared_kernel.application.ports import Clock, IdGenerator


class InventoryWork(InventoryUnitOfWork, Protocol):
    """The inventory unit of work as the unit use cases see it: with its `units` repository.

    The shared `InventoryUnitOfWork` port gains `units` when its SQL side lands (task 8); until
    then this local extension lets these use cases type `work.units` without the concrete unit
    of work having to satisfy a property it can't answer yet.
    """

    @property
    def units(self) -> Units: ...


type UnitOfWorkFactory = Callable[[WorkspaceId], InventoryWork]


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
    catalog doesn't know is a 404 (`PartNotFoundError`, 1.3), and a lot-counted part is a 422
    (`ReceiveAsLotError`, 1.5) — the mirror of the lot receive's `ReceiveAsUnitsError`. Then
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
        quantity = len(receipt.units)
        async with self._unit_of_work(workspace_id) as work:
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
                change=quantity,
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
            await work.commit()
            return UnitsReceived(units=tuple(created), balance=balance)


async def _check_unit_tracked(parts: Parts, workspace_id: WorkspaceId, part_id: PartId) -> None:
    """A part must exist and be unit-tracked before a unit receive (1.3, 1.5).

    The mirror of the lot receive's `_check_lot_counted`: a part the catalog doesn't know is a
    404, and a lot-counted part is a 422 `ReceiveAsLotError` — it takes the loose lot receive.
    """
    info = await parts.describe(workspace_id, part_id)
    if not info.exists:
        raise PartNotFoundError("no such part in this workspace")
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
