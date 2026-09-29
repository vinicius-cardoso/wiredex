"""`InventoryBuildStock` and `CatalogBuildParts`: three modules' stock in projects' words.

These are where inventory's `RevisionStock` and catalog's `describe_parts` become projects'
`BuildStock` and `BuildParts` (10-build-lifecycle decision 8). The translation is where a bug
would live, so the tests drive a real `RevisionStock` over the inventory fakes and a real
`describe_parts` over the catalog fakes — as the shared session drives them over the SQL
repositories — and check the ids, types and errors cross both ways.

The one-transaction wiring itself, `SqlBuildUnitOfWork` over one session, is proved in
`tests/integration/test_build_transactions.py`, where a real session can roll back.
"""

from uuid import uuid7

import pytest

from support.catalog import World as CatalogWorld
from support.identity import ManualClock, NewIds
from support.inventory import (
    NOW,
    InMemoryInventory,
)
from wiredex.bootstrap.build import CatalogBuildParts, InventoryBuildStock
from wiredex.inventory.application.builds import RevisionStock
from wiredex.inventory.domain.errors import ConcurrentStockError, LocationNotFoundError
from wiredex.inventory.domain.ledger import StockMovement
from wiredex.inventory.domain.location import Location
from wiredex.inventory.domain.lot import StockBalance, StockLot
from wiredex.inventory.domain.unit import Unit, UnitStatus
from wiredex.inventory.domain.values import (
    LocationId,
    LocationName,
    MovementKind,
    ShortCode,
    StockLotId,
    StockMovementId,
    UnitId,
)
from wiredex.inventory.domain.values import PartId as InventoryPartId
from wiredex.inventory.domain.values import RevisionId as InventoryRevisionId
from wiredex.inventory.domain.values import (
    WorkspaceId as InventoryWorkspaceId,
)
from wiredex.projects.domain.lifecycle import (
    StockChangedError,
    UnknownLocationError,
)
from wiredex.projects.domain.reservation import LotPick, Reservation
from wiredex.projects.domain.values import (
    LocationId as ProjectsLocationId,
)
from wiredex.projects.domain.values import PartId as ProjectsPartId
from wiredex.projects.domain.values import RevisionId as ProjectsRevisionId
from wiredex.projects.domain.values import UnitId as ProjectsUnitId

pytestmark = pytest.mark.anyio

BENCH = InventoryWorkspaceId(uuid7())


# --- CatalogBuildParts ----------------------------------------------------------------------


class TestCatalogBuildParts:
    async def test_describes_a_part_with_its_flags_in_projects_words(self) -> None:
        # A part crosses as projects' PartId, its category's flags as PartFacts (decision 8).
        world = CatalogWorld()
        boards = world.add_category("Boards")
        boards.tracked_individually = True  # the flag lives on the category
        part = world.add_part(boards, "ESP32 board")

        parts = CatalogBuildParts(world.catalog)
        facts = await parts.describe([ProjectsPartId(part.id)])

        described = facts[ProjectsPartId(part.id)]
        assert described.part_id == ProjectsPartId(part.id)
        assert described.name == "ESP32 board"
        assert described.tracked_individually is True
        assert described.not_stocked is False

    async def test_a_consumables_not_stocked_flag_is_carried(self) -> None:
        world = CatalogWorld()
        world.passives.not_stocked = True  # Resistors inherits it along the chain
        part = world.add_part(world.resistors, "Jumper wire")

        facts = await CatalogBuildParts(world.catalog).describe([ProjectsPartId(part.id)])

        assert facts[ProjectsPartId(part.id)].not_stocked is True

    async def test_a_part_the_workspace_doesnt_hold_is_left_out(self) -> None:
        # An unknown part is absent, which projects reads as an unknown part (09's 9.3).
        world = CatalogWorld()

        facts = await CatalogBuildParts(world.catalog).describe([ProjectsPartId(uuid7())])

        assert facts == {}

    async def test_no_part_ids_asks_nothing(self) -> None:
        world = CatalogWorld()
        assert await CatalogBuildParts(world.catalog).describe([]) == {}


# --- InventoryBuildStock ---------------------------------------------------------------------


def a_stock(inventory: InMemoryInventory) -> InventoryBuildStock:
    """`InventoryBuildStock` over a `RevisionStock` on the inventory fakes, as
    `bootstrap/build.py` binds it over `SqlInventoryRepositories`."""
    revision_stock = RevisionStock(inventory, BENCH, ManualClock(NOW), NewIds())
    return InventoryBuildStock(revision_stock)


def a_location(inventory: InMemoryInventory, code: str, name: str) -> Location:
    location = Location(LocationId(uuid7()), BENCH, None, ShortCode(code), LocationName(name), NOW)
    inventory.locations.saved[location.id] = location
    return location


def a_lot(
    inventory: InMemoryInventory, part_id: InventoryPartId, location: Location, on_hand: int
) -> StockLot:
    lot = StockLot(StockLotId(uuid7()), BENCH, part_id, location.id, NOW)
    inventory.lots.saved[lot.id] = lot
    movement = StockMovement(
        StockMovementId(uuid7()),
        BENCH,
        lot.id,
        MovementKind.RECEIVE,
        on_hand,
        None,
        None,
        None,
        None,
        NOW,
    )
    inventory.balances.saved[lot.id] = StockBalance.opening(lot.id).apply(movement)
    return lot


def a_unit(
    inventory: InMemoryInventory, part_id: InventoryPartId, lot: StockLot, code: str
) -> Unit:
    unit = Unit(
        UnitId(uuid7()),
        BENCH,
        part_id,
        lot.id,
        ShortCode(code),
        None,
        None,
        UnitStatus.IN_STOCK,
        NOW,
    )
    inventory.units.saved[unit.id] = unit
    return unit


class TestAvailableAndReserve:
    async def test_available_answers_reservable_stock_in_projects_terms(self) -> None:
        # Requirement 2.1: each lot's available (on hand less reserved) and its in-stock units.
        inventory = InMemoryInventory()
        part = InventoryPartId(uuid7())
        drawer = a_location(inventory, "WX-L-0001", "Drawer")
        # A loose lot: on hand with no units, so the recount leaves `changed` False.
        a_lot(inventory, part, drawer, on_hand=5)
        board_lot = a_lot(inventory, part, a_location(inventory, "WX-L-0002", "Shelf"), on_hand=1)
        unit = a_unit(inventory, part, board_lot, "WX-U-0001")
        stock = a_stock(inventory)

        reservable = await stock.available([ProjectsPartId(part)], [])

        assert sorted(lot.available for lot in reservable.lots) == [1, 5]
        assert {lot.part_id for lot in reservable.lots} == {ProjectsPartId(part)}
        assert {lot.location_code for lot in reservable.lots} == {"WX-L-0001", "WX-L-0002"}
        assert [u.code for u in reservable.units] == ["WX-U-0001"]
        assert reservable.units[0].unit_id == ProjectsUnitId(unit.id)
        assert reservable.units[0].in_stock is True
        assert reservable.changed is False
        assert reservable.now == NOW

    async def test_a_named_unit_crosses_into_named(self) -> None:
        inventory = InMemoryInventory()
        part = InventoryPartId(uuid7())
        drawer = a_location(inventory, "WX-L-0001", "Drawer")
        lot = a_lot(inventory, part, drawer, on_hand=1)
        unit = a_unit(inventory, part, lot, "WX-U-0001")
        stock = a_stock(inventory)

        reservable = await stock.available([ProjectsPartId(part)], [ProjectsUnitId(unit.id)])

        assert ProjectsUnitId(unit.id) in reservable.named

    async def test_reserve_writes_the_choice_kept_from_available(self) -> None:
        # Requirements 2.4, 2.6, 3.1: the pick's quantity is reserved and the unit linked.
        inventory = InMemoryInventory()
        part = InventoryPartId(uuid7())
        drawer = a_location(inventory, "WX-L-0001", "Drawer")
        lot = a_lot(inventory, part, drawer, on_hand=1)
        unit = a_unit(inventory, part, lot, "WX-U-0001")
        stock = a_stock(inventory)
        revision = ProjectsRevisionId(uuid7())

        await stock.available([ProjectsPartId(part)], [])
        pick = LotPick(lot_id=lot.id, quantity=1, unit_ids=(ProjectsUnitId(unit.id),))  # type: ignore[arg-type]
        await stock.reserve(revision, Reservation((pick,)))

        assert int(inventory.balances.saved[lot.id].reserved) == 1
        assert inventory.units.saved[unit.id].status is UnitStatus.RESERVED
        assert inventory.units.saved[unit.id].revision_id == InventoryRevisionId(revision)

    async def test_reserve_before_available_is_a_bug(self) -> None:
        inventory = InMemoryInventory()
        stock = a_stock(inventory)
        with pytest.raises(RuntimeError, match="available"):
            await stock.reserve(ProjectsRevisionId(uuid7()), Reservation(()))


class TestHoldingsAndUnits:
    async def test_release_consume_and_the_folds_cross_back(self) -> None:
        # Requirements 4.1, 5.1, 8.5: after a reserve, holdings fold back in projects' terms.
        inventory = InMemoryInventory()
        part = InventoryPartId(uuid7())
        drawer = a_location(inventory, "WX-L-0001", "Drawer")
        lot = a_lot(inventory, part, drawer, on_hand=4)
        stock = a_stock(inventory)
        revision = ProjectsRevisionId(uuid7())

        await stock.available([ProjectsPartId(part)], [])
        await stock.reserve(revision, Reservation((LotPick(lot.id, 2, ()),)))  # type: ignore[arg-type]

        holdings = await stock.holdings(revision)
        assert {h.part_id: h.quantity for h in holdings.reserved} == {ProjectsPartId(part): 2}
        assert holdings.reserved[0].location_code == "WX-L-0001"

        part_holdings = await stock.holdings_of_part(ProjectsPartId(part))
        assert part_holdings[0].revision_id == revision
        assert part_holdings[0].reserved == 2

        # Consume, then the holding is a consumption.
        now = await stock.consume(revision)
        assert now == NOW
        after = await stock.holdings(revision)
        assert after.consumed == {ProjectsPartId(part): 2}
        assert after.reserved == ()

    async def test_units_of_crosses_to_held_units(self) -> None:
        # Requirement 3.11: the revision's units in projects' words, with the location code.
        inventory = InMemoryInventory()
        part = InventoryPartId(uuid7())
        drawer = a_location(inventory, "WX-L-0001", "Drawer")
        lot = a_lot(inventory, part, drawer, on_hand=1)
        unit = a_unit(inventory, part, lot, "WX-U-0001")
        stock = a_stock(inventory)
        revision = ProjectsRevisionId(uuid7())

        await stock.available([ProjectsPartId(part)], [])
        await stock.reserve(
            revision,
            Reservation((LotPick(lot.id, 1, (ProjectsUnitId(unit.id),)),)),  # type: ignore[arg-type]
        )

        held = await stock.units_of(revision)
        assert [u.code for u in held] == ["WX-U-0001"]
        assert held[0].unit_id == ProjectsUnitId(unit.id)
        assert held[0].part_id == ProjectsPartId(part)
        assert held[0].location_code == "WX-L-0001"


class TestReturnAndErrors:
    async def test_dismantle_returns_to_a_location_and_answers_the_time(self) -> None:
        # Requirements 6.2, 6.3: build then dismantle returns the stock to a chosen location.
        inventory = InMemoryInventory()
        part = InventoryPartId(uuid7())
        drawer = a_location(inventory, "WX-L-0001", "Drawer")
        lab = a_location(inventory, "WX-L-0002", "Lab")
        lot = a_lot(inventory, part, drawer, on_hand=10)
        stock = a_stock(inventory)
        revision = ProjectsRevisionId(uuid7())

        await stock.available([ProjectsPartId(part)], [])
        await stock.reserve(revision, Reservation((LotPick(lot.id, 4, ()),)))  # type: ignore[arg-type]
        await stock.consume(revision)
        now = await stock.return_to(revision, ProjectsLocationId(lab.id))

        assert now == NOW
        return_lot = await inventory.lots.for_part_at(part, lab.id)
        assert return_lot is not None
        assert int(inventory.balances.saved[return_lot.id].on_hand) == 4

    async def test_an_unknown_location_becomes_unknown_location(self) -> None:
        # Requirement 6.1, 11.2: inventory's not-found becomes projects' unknown_location.
        inventory = InMemoryInventory()
        part = InventoryPartId(uuid7())
        drawer = a_location(inventory, "WX-L-0001", "Drawer")
        lot = a_lot(inventory, part, drawer, on_hand=5)
        stock = a_stock(inventory)
        revision = ProjectsRevisionId(uuid7())
        await stock.available([ProjectsPartId(part)], [])
        await stock.reserve(revision, Reservation((LotPick(lot.id, 1, ()),)))  # type: ignore[arg-type]
        await stock.consume(revision)

        with pytest.raises(UnknownLocationError):
            await stock.return_to(revision, ProjectsLocationId(uuid7()))

    @pytest.mark.parametrize(
        ("raised", "translated"),
        [
            (LocationNotFoundError("gone"), UnknownLocationError),
            (ConcurrentStockError("raced"), StockChangedError),
        ],
    )
    async def test_return_to_translates_inventorys_errors(
        self, raised: Exception, translated: type[Exception]
    ) -> None:
        # The two errors a return can surface become projects' codes (Error Handling); anything
        # else would be a bug and pass straight through as a 500.
        stock = InventoryBuildStock(_RaisingStock(raised))  # type: ignore[arg-type]

        with pytest.raises(translated):
            await stock.return_to(ProjectsRevisionId(uuid7()), ProjectsLocationId(uuid7()))


class _RaisingStock:
    """A `RevisionStock` whose `return_to` raises, to pin `InventoryBuildStock`'s error map."""

    def __init__(self, error: Exception) -> None:
        self._error = error

    async def return_to(self, *_args: object) -> object:
        raise self._error
