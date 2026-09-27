"""In-memory stand-ins for the inventory ports, shared by the use-case tests.

Each store is one workspace's rows, because that is what a real inventory unit of work sees
(ADR 0007): the workspace it was opened for is recorded rather than filtered on, so a test
can still assert that a use case scoped itself to the caller's bench.

The `Parts` port is faked here rather than reaching into catalog: inventory never imports
catalog, and its use cases only ever learn `PartStockInfo` about a part. The fake is seeded
with one lot-counted part and one unit-tracked part, the two answers a receive branches on.
"""

from collections.abc import AsyncIterator, Iterable, Sequence
from datetime import UTC, datetime
from types import TracebackType
from typing import Self
from uuid import uuid7

from support.identity import ManualClock, NewIds
from wiredex.inventory.api.router import InventoryUseCases
from wiredex.inventory.application.locations import (
    CreateLocation,
    DeleteLocation,
    ListLocations,
    MoveLocation,
    RenameLocation,
)
from wiredex.inventory.application.movements import AdjustStock, MoveStock, ReceiveStock
from wiredex.inventory.application.ports import (
    LotBalance,
    PartStockInfo,
    ShortCodeKind,
)
from wiredex.inventory.application.stock import PartStock, PartTotals
from wiredex.inventory.application.units import (
    DeleteUnit,
    ListUnitsOfLocation,
    ListUnitsOfPart,
    MoveUnit,
    ReceiveUnits,
    RelabelUnit,
    RetireUnit,
    SearchUnits,
    UnretireUnit,
)
from wiredex.inventory.domain.errors import ConcurrentStockError
from wiredex.inventory.domain.ledger import StockMovement
from wiredex.inventory.domain.location import Location
from wiredex.inventory.domain.lot import StockBalance, StockLot
from wiredex.inventory.domain.unit import Unit, UnitStatus
from wiredex.inventory.domain.values import (
    LocationId,
    LocationName,
    Mac,
    PartId,
    Quantity,
    Serial,
    ShortCode,
    StockLotId,
    UnitId,
    WorkspaceId,
)

NOW = datetime(2026, 9, 25, 10, 0, tzinfo=UTC)
BENCH = WorkspaceId(uuid7())

# Two parts the fake catalog knows: one counted in lots, one tracked as individual units.
# A receive branches on exactly this difference (requirement 6.3).
LOT_COUNTED_PART = PartId(uuid7())
UNIT_TRACKED_PART = PartId(uuid7())


class InMemoryLocations:
    def __init__(self) -> None:
        self.saved: dict[LocationId, Location] = {}
        self._lot_locations: set[LocationId] = set()

    async def add(self, location: Location) -> None:
        self.saved[location.id] = location

    async def get(self, location_id: LocationId) -> Location | None:
        return self.saved.get(location_id)

    async def all(self) -> list[Location]:
        return list(self.saved.values())

    async def ancestors(self, location_id: LocationId) -> list[Location]:
        # Root first, as the recursive query returns it.
        chain: list[Location] = []
        current = self.saved.get(location_id)
        while current is not None and current.parent_id is not None:
            current = self.saved.get(current.parent_id)
            if current is not None:
                chain.append(current)
        chain.reverse()
        return chain

    async def children_of(self, location_id: LocationId) -> list[Location]:
        return [child for child in self.saved.values() if child.parent_id == location_id]

    async def sibling_named(
        self, parent_id: LocationId | None, name: LocationName
    ) -> Location | None:
        siblings = (
            loc for loc in self.saved.values() if loc.parent_id == parent_id and loc.name == name
        )
        return next(siblings, None)

    async def has_lots(self, location_id: LocationId) -> bool:
        return location_id in self._lot_locations

    async def remove(self, location: Location) -> None:
        del self.saved[location.id]


class InMemoryLots:
    def __init__(self) -> None:
        self.saved: dict[StockLotId, StockLot] = {}

    async def get(self, lot_id: StockLotId) -> StockLot | None:
        return self.saved.get(lot_id)

    async def for_part_at(self, part_id: PartId, location_id: LocationId) -> StockLot | None:
        lots = (
            lot
            for lot in self.saved.values()
            if lot.part_id == part_id and lot.location_id == location_id
        )
        return next(lots, None)

    async def add(self, lot: StockLot) -> None:
        self.saved[lot.id] = lot


class InMemoryLedger:
    """Append-only: rows go in and are read back, never updated or deleted (ADR 0002)."""

    def __init__(self) -> None:
        self.saved: list[StockMovement] = []

    async def append(self, movement: StockMovement) -> None:
        self.saved.append(movement)

    async def movements_of(self, lot_id: StockLotId) -> list[StockMovement]:
        return [movement for movement in self.saved if movement.lot_id == lot_id]

    async def all(self) -> AsyncIterator[StockMovement]:
        # In insertion order, which is time order, as the SQL streams it for a rebuild.
        for movement in self.saved:
            yield movement


class InMemoryBalanceSheet:
    def __init__(self, lots: InMemoryLots, locations: InMemoryLocations) -> None:
        self.saved: dict[StockLotId, StockBalance] = {}
        # A balance is per lot, but a breakdown is per location: the sheet reads the lot to
        # find where its stock sits, as the SQL joins `stock_balances` to `stock_lots`.
        self._lots = lots
        self._locations = locations

    async def get(self, lot_id: StockLotId) -> StockBalance | None:
        return self.saved.get(lot_id)

    async def put(self, balance: StockBalance) -> None:
        # As the SQL sheet: a balance whose version doesn't follow the stored one is refused.
        stored = self.saved.get(balance.lot_id)
        if stored is not None and stored.version != balance.version - 1:
            raise ConcurrentStockError("the stock changed while this was being saved; try again")
        self.saved[balance.lot_id] = balance

    async def totals_by_part(self, part_ids: Sequence[PartId]) -> dict[PartId, int]:
        wanted = set(part_ids)
        totals: dict[PartId, int] = {}
        for lot_id, balance in self.saved.items():
            lot = self._lots.saved.get(lot_id)
            if lot is not None and lot.part_id in wanted:
                totals[lot.part_id] = totals.get(lot.part_id, 0) + int(balance.on_hand)
        return totals

    async def by_part(self, part_id: PartId) -> list[LotBalance]:
        breakdown: list[LotBalance] = []
        for lot_id, balance in self.saved.items():
            lot = self._lots.saved.get(lot_id)
            if lot is None or lot.part_id != part_id:
                continue
            location = self._locations.saved.get(lot.location_id)
            if location is not None:
                breakdown.append(LotBalance(location, balance.on_hand))
        return breakdown

    async def replace_all(self, balances: Iterable[StockBalance]) -> None:
        self.saved = {balance.lot_id: balance for balance in balances}


class InMemoryShortCodes:
    """A per-kind counter, gap-free within a workspace, as the `ON CONFLICT` counter is."""

    def __init__(self) -> None:
        self._next: dict[ShortCodeKind, int] = {}

    async def next(self, kind: ShortCodeKind) -> int:
        current = self._next.get(kind, 1)
        self._next[kind] = current + 1
        return current


class InMemoryUnits:
    """One workspace's units. Search and the two uniqueness checks fold case as the SQL does.

    `serial_taken` compares on `Serial.fold()`, the per-part lower-cased index; `mac_taken`
    compares on the already-canonical stored MAC, the per-workspace index. `search` matches
    the term against code, serial and MAC as a case-insensitive substring (requirement 6.3).
    """

    def __init__(self, lots: InMemoryLots) -> None:
        self.saved: dict[UnitId, Unit] = {}
        # A unit's location is its lot's location, so `of_location` reads the lots to find
        # where each unit sits, as the SQL joins `units` to `stock_lots`.
        self._lots = lots

    async def get(self, unit_id: UnitId) -> Unit | None:
        return self.saved.get(unit_id)

    async def add(self, unit: Unit) -> None:
        self.saved[unit.id] = unit

    async def of_part(self, part_id: PartId) -> list[Unit]:
        return [unit for unit in self.saved.values() if unit.part_id == part_id]

    async def of_lot(self, lot_id: StockLotId) -> list[Unit]:
        return [unit for unit in self.saved.values() if unit.lot_id == lot_id]

    async def of_location(self, location_id: LocationId) -> list[Unit]:
        lots_here = {
            lot_id for lot_id, lot in self._lots.saved.items() if lot.location_id == location_id
        }
        return [unit for unit in self.saved.values() if unit.lot_id in lots_here]

    async def in_stock_at(self, lot_id: StockLotId) -> int:
        return sum(
            1
            for unit in self.saved.values()
            if unit.lot_id == lot_id and unit.status is UnitStatus.IN_STOCK
        )

    async def search(self, term: str) -> list[Unit]:
        needle = term.lower()
        return [unit for unit in self.saved.values() if _matches(unit, needle)]

    async def serial_taken(self, part_id: PartId, serial: Serial) -> bool:
        folded = serial.fold()
        return any(
            unit.part_id == part_id and unit.serial is not None and unit.serial.fold() == folded
            for unit in self.saved.values()
        )

    async def mac_taken(self, mac: Mac) -> bool:
        return any(unit.mac == mac for unit in self.saved.values())

    async def remove(self, unit: Unit) -> None:
        del self.saved[unit.id]


def _matches(unit: Unit, needle: str) -> bool:
    """Whether the unit's code, serial or MAC contains the lower-cased term."""
    haystacks = [str(unit.code)]
    if unit.serial is not None:
        haystacks.append(str(unit.serial))
    if unit.mac is not None:
        haystacks.append(str(unit.mac))
    return any(needle in field.lower() for field in haystacks)


class FakeParts:
    """The catalog `Parts` port, seeded with the two answers a receive branches on.

    A part the fake wasn't told about answers `exists=False`, the 404 path (requirement 4.2).
    """

    def __init__(self) -> None:
        self.known: dict[PartId, bool] = {
            LOT_COUNTED_PART: False,
            UNIT_TRACKED_PART: True,
        }

    async def describe(self, workspace_id: WorkspaceId, part_id: PartId) -> PartStockInfo:  # noqa: ARG002  the Parts port shape
        if part_id not in self.known:
            return PartStockInfo(exists=False, tracked_individually=False)
        return PartStockInfo(exists=True, tracked_individually=self.known[part_id])


class InMemoryInventory:
    """A unit of work over shared in-memory stores; counts commits and who it was opened for.

    The repositories are exposed as plain attributes, which satisfy the read-only properties
    the `InventoryUnitOfWork` protocol declares — a fake stands in for the whole shape.
    """

    def __init__(self) -> None:
        self.locations = InMemoryLocations()
        self.lots = InMemoryLots()
        self.ledger = InMemoryLedger()
        self.balances = InMemoryBalanceSheet(self.lots, self.locations)
        self.short_codes = InMemoryShortCodes()
        self.units = InMemoryUnits(self.lots)
        self.commits = 0
        self.opened_for: list[WorkspaceId] = []

    def for_workspace(self, workspace_id: WorkspaceId) -> Self:
        """The `UnitOfWorkFactory` a use case takes, recording the bench it asked for."""
        self.opened_for.append(workspace_id)
        return self

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def clear(self) -> None:
        """Empty every store, as the SQL unit of work clears a bench for a demo reset (8.6)."""
        self.locations.saved.clear()
        self.locations._lot_locations.clear()
        self.lots.saved.clear()
        self.ledger.saved.clear()
        self.balances.saved.clear()
        self.short_codes._next.clear()
        self.units.saved.clear()


class World:
    """The inventory fakes over a bench that already holds *Lab → Drawer 3*.

    The seed is written straight to the stores, not through use cases: a test of one use
    case shouldn't depend on another one working, and the tree is the same either way.
    """

    def __init__(self) -> None:
        self.inventory = InMemoryInventory()
        self.parts = FakeParts()
        self.clock = ManualClock(NOW)
        self.ids = NewIds()
        self._code = 0
        self._unit_code = 0
        self.lab = self.add_location("Lab")
        self.drawer = self.add_location("Drawer 3", self.lab)
        work = self.inventory.for_workspace
        self.create_location = CreateLocation(work, self.clock, self.ids)
        self.rename_location = RenameLocation(work)
        self.move_location = MoveLocation(work)
        self.delete_location = DeleteLocation(work)
        self.list_locations = ListLocations(work)
        self.receive_stock = ReceiveStock(work, self.parts, self.clock, self.ids)
        self.adjust_stock = AdjustStock(work, self.parts, self.clock, self.ids)
        self.move_stock = MoveStock(work, self.clock, self.ids)
        self.part_stock = PartStock(work)
        self.part_totals = PartTotals(work)
        self.receive_units = ReceiveUnits(work, self.parts, self.clock, self.ids)
        self.relabel_unit = RelabelUnit(work)
        self.retire_unit = RetireUnit(work, self.clock, self.ids)
        self.unretire_unit = UnretireUnit(work, self.clock, self.ids)
        self.move_unit = MoveUnit(work, self.move_stock, self.clock, self.ids)
        self.delete_unit = DeleteUnit(work)
        self.list_units_of_part = ListUnitsOfPart(work)
        self.list_units_of_location = ListUnitsOfLocation(work)
        self.search_units = SearchUnits(work)

    def inventory_use_cases(self) -> InventoryUseCases:
        """What `create_router` takes, so the API test mounts these same fakes."""
        return InventoryUseCases(
            create_location=self.create_location,
            rename_location=self.rename_location,
            move_location=self.move_location,
            delete_location=self.delete_location,
            list_locations=self.list_locations,
            receive_stock=self.receive_stock,
            adjust_stock=self.adjust_stock,
            move_stock=self.move_stock,
            part_stock=self.part_stock,
            part_totals=self.part_totals,
        )

    def add_location(self, name: str, parent: Location | None = None) -> Location:
        self._code += 1
        location = Location(
            LocationId(uuid7()),
            BENCH,
            None if parent is None else parent.id,
            ShortCode.for_location(self._code),
            LocationName(name),
            self.clock.now(),
        )
        self.inventory.locations.saved[location.id] = location
        return location

    def hold_lot(self, part_id: PartId, location: Location, on_hand: int = 0) -> StockLot:
        """Seed a lot with a balance, marking its location as holding stock (`has_lots`)."""
        lot = StockLot(StockLotId(uuid7()), BENCH, part_id, location.id, self.clock.now())
        self.inventory.lots.saved[lot.id] = lot
        self.inventory.balances.saved[lot.id] = StockBalance(
            lot_id=lot.id, on_hand=Quantity(on_hand), reserved=Quantity(0), version=0
        )
        self.inventory.locations._lot_locations.add(location.id)
        return lot

    def hold_unit(
        self,
        part_id: PartId,
        lot: StockLot,
        *,
        status: UnitStatus = UnitStatus.IN_STOCK,
        serial: Serial | None = None,
        mac: Mac | None = None,
    ) -> Unit:
        """Seed a unit pointing at a lot, minting the next `WX-U-NNNN` code for this world."""
        self._unit_code += 1
        unit = Unit(
            id=UnitId(uuid7()),
            workspace_id=BENCH,
            part_id=part_id,
            lot_id=lot.id,
            code=ShortCode.for_unit(self._unit_code),
            serial=serial,
            mac=mac,
            status=status,
            created_at=self.clock.now(),
        )
        self.inventory.units.saved[unit.id] = unit
        return unit
