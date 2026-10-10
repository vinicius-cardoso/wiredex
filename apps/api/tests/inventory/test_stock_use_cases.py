"""Reading a part's stock and rebuilding the projection from the ledger.

`PartStock` reads the balance sheet: a total and a per-location breakdown, and zero with an
empty breakdown for a part never received (requirement 7.4). `RebuildBalances` streams the
ledger and folds it back, so the projection it writes equals the one written incrementally —
property 6, the ledger's proof of itself.
"""

from uuid import uuid7

import anyio
import pytest
from hypothesis import given
from hypothesis import strategies as st

from support.inventory import (
    BENCH,
    CONSUMABLE_PART,
    LOT_COUNTED_PART,
    TRACKED_CONSUMABLE_PART,
    UNIT_TRACKED_PART,
    InMemoryInventory,
    World,
)
from wiredex.inventory.application.stock import (
    AvailableStock,
    CountStockByKind,
    PartStock,
    RebuildBalances,
    StockCounting,
    StockedParts,
)
from wiredex.inventory.application.units import NewUnit, UnitReceipt
from wiredex.inventory.domain.errors import LocationNotFoundError
from wiredex.inventory.domain.ledger import StockMovement
from wiredex.inventory.domain.lot import StockBalance
from wiredex.inventory.domain.unit import UnitStatus
from wiredex.inventory.domain.values import (
    LocationId,
    MovementKind,
    PartId,
    Quantity,
    StockLotId,
    StockMovementId,
)

pytestmark = pytest.mark.anyio


def movement(lot_id: StockLotId, change: int) -> StockMovement:
    """A bare ledger row carrying just its lot and signed change, which is all a fold reads."""
    return StockMovement(
        id=StockMovementId(uuid7()),
        workspace_id=BENCH,
        lot_id=lot_id,
        kind=MovementKind.RECEIVE if change >= 0 else MovementKind.ADJUST,
        change=change,
        reason=None,
        note=None,
        move_group=None,
        revision_id=None,
        created_at=World().clock.now(),
    )


class TestPartStock:
    async def test_reports_the_total_summed_across_lots(self) -> None:
        world = World()
        world.hold_lot(LOT_COUNTED_PART, world.lab, on_hand=150)
        world.hold_lot(LOT_COUNTED_PART, world.drawer, on_hand=30)
        stock = PartStock(world.inventory.for_workspace)

        view = await stock(BENCH, LOT_COUNTED_PART)

        assert view.total == 180

    async def test_breaks_the_total_down_by_location(self) -> None:
        world = World()
        world.hold_lot(LOT_COUNTED_PART, world.lab, on_hand=150)
        world.hold_lot(LOT_COUNTED_PART, world.drawer, on_hand=30)
        stock = PartStock(world.inventory.for_workspace)

        view = await stock(BENCH, LOT_COUNTED_PART)

        by_location = {row.location.id: int(row.on_hand) for row in view.breakdown}
        assert by_location == {world.lab.id: 150, world.drawer.id: 30}

    async def test_each_breakdown_row_carries_its_location(self) -> None:
        # The breakdown pairs a count with the location it sits in, code and name (7.3).
        world = World()
        world.hold_lot(LOT_COUNTED_PART, world.drawer, on_hand=30)
        stock = PartStock(world.inventory.for_workspace)

        view = await stock(BENCH, LOT_COUNTED_PART)

        (row,) = view.breakdown
        assert row.location.name == world.drawer.name
        assert row.location.code == world.drawer.code

    async def test_a_never_received_part_reads_as_zero_and_empty(self) -> None:
        # Not an error: a part with no lot answers a total of zero, an empty breakdown (7.4).
        world = World()
        stock = PartStock(world.inventory.for_workspace)

        view = await stock(BENCH, PartId(uuid7()))

        assert view.total == 0
        assert view.breakdown == []

    async def test_scopes_the_read_to_the_callers_workspace(self) -> None:
        world = World()
        stock = PartStock(world.inventory.for_workspace)

        await stock(BENCH, LOT_COUNTED_PART)

        assert world.inventory.opened_for == [BENCH]

    async def test_reading_stock_commits_nothing(self) -> None:
        world = World()
        world.hold_lot(LOT_COUNTED_PART, world.lab, on_hand=5)
        stock = PartStock(world.inventory.for_workspace)

        await stock(BENCH, LOT_COUNTED_PART)

        assert world.inventory.commits == 0


class TestLocationStock:
    async def test_lists_each_lot_in_the_location_by_part_name(self) -> None:
        # What the drawer holds: the boards before the resistor, by name, and nothing of the
        # lab above it; one read of the names for every lot.
        world = World()
        world.hold_lot(LOT_COUNTED_PART, world.drawer, on_hand=30, reserved=4)
        world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=2)
        world.hold_lot(CONSUMABLE_PART, world.lab, on_hand=1)

        lots = await world.location_stock(BENCH, world.drawer.id)

        assert [(lot.part_name, int(lot.holding.on_hand)) for lot in lots] == [
            ("10k resistor", 30),
            ("ESP32 DevKit", 2),
        ]
        assert int(lots[0].holding.reserved) == 4
        assert int(lots[0].holding.available) == 26
        assert world.parts.name_reads == [frozenset({LOT_COUNTED_PART, UNIT_TRACKED_PART})]
        assert world.inventory.commits == 0

    async def test_lists_a_part_the_catalog_no_longer_names_last(self) -> None:
        world = World()
        gone = PartId(uuid7())
        world.hold_lot(gone, world.drawer, on_hand=7)
        world.hold_lot(LOT_COUNTED_PART, world.drawer, on_hand=1)

        lots = await world.location_stock(BENCH, world.drawer.id)

        assert [lot.part_name for lot in lots] == ["10k resistor", None]

    async def test_an_empty_location_holds_nothing_and_asks_no_names(self) -> None:
        world = World()

        assert await world.location_stock(BENCH, world.lab.id) == []
        assert world.parts.name_reads == []

    async def test_a_location_the_workspace_doesnt_hold_is_not_found(self) -> None:
        world = World()

        with pytest.raises(LocationNotFoundError):
            await world.location_stock(BENCH, LocationId(uuid7()))


class TestCountStockByKind:
    async def test_tells_a_parts_loose_pieces_from_its_units(self) -> None:
        # What the catalog asks before a part changes between counted and tracked. A lot's
        # on_hand holds its in-stock and reserved units, so the rest of it is loose.
        world = World()
        world.hold_lot(LOT_COUNTED_PART, world.lab, on_hand=12)
        boards = world.hold_lot(UNIT_TRACKED_PART, world.lab, on_hand=2)
        world.hold_unit(UNIT_TRACKED_PART, boards)
        world.hold_unit(UNIT_TRACKED_PART, boards, status=UnitStatus.RESERVED)
        world.hold_unit(UNIT_TRACKED_PART, boards, status=UnitStatus.IN_USE)
        world.hold_unit(UNIT_TRACKED_PART, boards, status=UnitStatus.RETIRED)
        # Counted loose before it was tracked: three pieces, one of them now a unit.
        mixed = world.hold_lot(TRACKED_CONSUMABLE_PART, world.drawer, on_hand=3)
        world.hold_unit(TRACKED_CONSUMABLE_PART, mixed)
        world.hold_lot(CONSUMABLE_PART, world.lab, on_hand=0)
        count = CountStockByKind(world.inventory.for_workspace)
        parts = [LOT_COUNTED_PART, UNIT_TRACKED_PART, TRACKED_CONSUMABLE_PART, CONSUMABLE_PART]

        assert await count(BENCH, parts) == {
            LOT_COUNTED_PART: StockCounting(loose=12, units=0),
            # A retired unit is out for good and counts as neither.
            UNIT_TRACKED_PART: StockCounting(loose=0, units=3),
            TRACKED_CONSUMABLE_PART: StockCounting(loose=2, units=1),
        }
        assert world.inventory.commits == 0

    async def test_asked_of_no_part_it_opens_nothing(self) -> None:
        world = World()
        assert await CountStockByKind(world.inventory.for_workspace)(BENCH, []) == {}
        assert world.inventory.opened_for == []


class TestStockedParts:
    async def test_names_every_part_whose_lots_hold_stock(self) -> None:
        # The parts list's stock filter: a part held in two places counts once, a part whose
        # only lot is empty doesn't, and the read commits nothing.
        world = World()
        world.hold_lot(LOT_COUNTED_PART, world.lab, on_hand=3)
        world.hold_lot(LOT_COUNTED_PART, world.drawer, on_hand=0)
        world.hold_lot(CONSUMABLE_PART, world.lab, on_hand=0)
        stocked = StockedParts(world.inventory.for_workspace)

        assert await stocked(BENCH) == frozenset({LOT_COUNTED_PART})
        assert world.inventory.opened_for == [BENCH]
        assert world.inventory.commits == 0

    async def test_a_bench_with_no_stock_names_no_part(self) -> None:
        world = World()

        assert await StockedParts(world.inventory.for_workspace)(BENCH) == frozenset()


class TestAvailableStock:
    async def test_sums_what_is_available_over_a_parts_lots(self) -> None:
        # 09's requirement 6.2: on hand less reserved, summed; what 10 will reserve is left out.
        world = World()
        lab = world.hold_lot(LOT_COUNTED_PART, world.lab, on_hand=150)
        world.hold_lot(LOT_COUNTED_PART, world.drawer, on_hand=30)
        world.inventory.balances.saved[lab.id] = StockBalance(
            lab.id, Quantity(150), Quantity(20), version=0
        )
        available = AvailableStock(world.inventory.for_workspace)

        assert await available(BENCH, [LOT_COUNTED_PART]) == {LOT_COUNTED_PART: 160}
        assert world.inventory.commits == 0

    async def test_a_part_no_lot_holds_is_absent(self) -> None:
        world = World()
        world.hold_lot(LOT_COUNTED_PART, world.lab, on_hand=5)
        available = AvailableStock(world.inventory.for_workspace)

        assert await available(BENCH, [LOT_COUNTED_PART, PartId(uuid7())]) == {LOT_COUNTED_PART: 5}

    async def test_no_ids_open_no_unit_of_work(self) -> None:
        world = World()
        available = AvailableStock(world.inventory.for_workspace)

        assert await available(BENCH, []) == {}
        assert world.inventory.opened_for == []

    async def test_a_unit_tracked_part_answers_its_in_stock_units(self) -> None:
        # 09's requirement 6.3: three received and one retired leaves two; un-retired, three.
        world = World()
        received = await world.receive_units(
            BENCH, UnitReceipt(UNIT_TRACKED_PART, world.drawer.id, (NewUnit(),) * 3)
        )
        available = AvailableStock(world.inventory.for_workspace)

        await world.retire_unit(BENCH, received.units[0].id)
        assert await available(BENCH, [UNIT_TRACKED_PART]) == {UNIT_TRACKED_PART: 2}

        await world.unretire_unit(BENCH, received.units[0].id)
        assert await available(BENCH, [UNIT_TRACKED_PART]) == {UNIT_TRACKED_PART: 3}


class TestRebuildBalances:
    async def test_replaces_the_projection_from_the_ledger(self) -> None:
        world = World()
        lot = world.hold_lot(LOT_COUNTED_PART, world.lab)
        await world.inventory.ledger.append(movement(lot.id, +100))
        await world.inventory.ledger.append(movement(lot.id, -40))
        # Tamper with the stored balance so a rebuild has something to correct: straight into
        # the fake's storage, since `put` refuses a version that doesn't follow the stored one.
        world.inventory.balances.saved[lot.id] = StockBalance(
            lot.id, Quantity(999), Quantity(0), version=7
        )
        rebuild = RebuildBalances(world.inventory.for_workspace)

        await rebuild(BENCH)

        rebuilt = await world.inventory.balances.get(lot.id)
        assert rebuilt is not None
        assert int(rebuilt.on_hand) == 60

    async def test_rebuilds_in_one_transaction_per_workspace(self) -> None:
        world = World()
        lot = world.hold_lot(LOT_COUNTED_PART, world.lab)
        await world.inventory.ledger.append(movement(lot.id, +5))
        rebuild = RebuildBalances(world.inventory.for_workspace)

        await rebuild(BENCH)

        assert world.inventory.commits == 1
        assert world.inventory.opened_for == [BENCH]

    async def test_an_empty_ledger_rebuilds_to_an_empty_projection(self) -> None:
        world = World()
        rebuild = RebuildBalances(world.inventory.for_workspace)

        await rebuild(BENCH)

        assert world.inventory.balances.saved == {}


# A ledger of accepted movements spread over a few lots: each lot's running sum stays at or
# above zero, so no fold hits the floor and every row is a movement a use case would accept —
# the space property 6 folds. `+quantity` rows model receives; a trailing `-quantity` bounded
# by what came before models an accepted withdrawal.
@st.composite
def accepted_ledger(draw: st.DrawFn) -> list[tuple[int, int]]:
    """Rows as `(lot_index, change)`, with each lot's cumulative on_hand never below zero."""
    lot_count = draw(st.integers(min_value=1, max_value=3))
    running = [0] * lot_count
    rows: list[tuple[int, int]] = []
    for _ in range(draw(st.integers(min_value=1, max_value=25))):
        lot_index = draw(st.integers(min_value=0, max_value=lot_count - 1))
        if running[lot_index] > 0 and draw(st.booleans()):
            change = -draw(st.integers(min_value=1, max_value=running[lot_index]))
        else:
            change = draw(st.integers(min_value=1, max_value=500))
        running[lot_index] += change
        rows.append((lot_index, change))
    return rows


class TestProperty6:
    @given(rows=accepted_ledger())
    def test_rebuild_reproduces_the_incremental_projection(
        self, rows: list[tuple[int, int]]
    ) -> None:
        """For any sequence of accepted movements, `wiredex stock rebuild` computes a
        projection equal to the one written incrementally, balance for balance.

        **Validates: Requirements 5.2, 5.3**
        """
        anyio.run(self._check, rows)

    @staticmethod
    async def _check(rows: list[tuple[int, int]]) -> None:
        world = World()
        lot_ids = [StockLotId(uuid7()) for _ in range(3)]

        # The incremental path: apply each movement and put the balance, as a receive does.
        # A balance only appears once a movement touches its lot, exactly as a receive writes
        # one — an untouched lot has no incremental balance, and none to rebuild either.
        incremental: dict[StockLotId, StockBalance] = {}
        for lot_index, change in rows:
            lot_id = lot_ids[lot_index]
            row = movement(lot_id, change)
            await world.inventory.ledger.append(row)
            current = incremental.get(lot_id) or StockBalance.opening(lot_id)
            incremental[lot_id] = current.apply(row)
            await world.inventory.balances.put(incremental[lot_id])

        incremental_projection = {
            lot_id: int(balance.on_hand)
            for lot_id, balance in world.inventory.balances.saved.items()
        }

        # Rebuild over a fresh sheet sharing the same ledger, so the comparison is the
        # incremental projection against a from-scratch one, not against itself.
        scratch = InMemoryInventory()
        scratch.ledger = world.inventory.ledger
        await RebuildBalances(scratch.for_workspace)(BENCH)
        rebuilt = {
            lot_id: int(balance.on_hand) for lot_id, balance in scratch.balances.saved.items()
        }

        assert rebuilt == incremental_projection
