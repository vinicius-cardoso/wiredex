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

from support.inventory import BENCH, LOT_COUNTED_PART, InMemoryInventory, World
from wiredex.inventory.application.stock import PartStock, RebuildBalances
from wiredex.inventory.domain.ledger import StockMovement
from wiredex.inventory.domain.lot import StockBalance
from wiredex.inventory.domain.values import (
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


class TestRebuildBalances:
    async def test_replaces_the_projection_from_the_ledger(self) -> None:
        world = World()
        lot = world.hold_lot(LOT_COUNTED_PART, world.lab)
        await world.inventory.ledger.append(movement(lot.id, +100))
        await world.inventory.ledger.append(movement(lot.id, -40))
        # Tamper with the stored balance so a rebuild has something to correct.
        await world.inventory.balances.put(
            StockBalance(lot.id, Quantity(999), Quantity(0), version=7)
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
