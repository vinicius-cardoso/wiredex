"""The three movement use cases: receive, adjust and move, over the in-memory fakes.

Each use case is one transaction, so the tests assert both the ledger row(s) and the balance
it moves, and that a refused movement writes neither. Property 5 pins the adjust: whatever
the previous count, an adjust reaches exactly the counted quantity and stores the delta.
"""

from uuid import uuid7

import anyio
import pytest
from hypothesis import given
from hypothesis import strategies as st

from support.inventory import (
    BENCH,
    LOT_COUNTED_PART,
    UNIT_TRACKED_PART,
    World,
)
from wiredex.inventory.application.movements import AdjustStock, MoveStock, ReceiveStock
from wiredex.inventory.application.ports import Adjustment, Move, Receipt
from wiredex.inventory.domain.errors import (
    InsufficientStockError,
    PartNotFoundError,
    ReceiveAsUnitsError,
    SameLocationError,
)
from wiredex.inventory.domain.values import (
    MovementKind,
    MovementReason,
    PartId,
    Quantity,
)

pytestmark = pytest.mark.anyio


def receive_stock(world: World) -> ReceiveStock:
    return ReceiveStock(world.inventory.for_workspace, world.parts, world.clock, world.ids)


def adjust_stock(world: World) -> AdjustStock:
    return AdjustStock(world.inventory.for_workspace, world.parts, world.clock, world.ids)


def move_stock(world: World) -> MoveStock:
    return MoveStock(world.inventory.for_workspace, world.parts, world.clock, world.ids)


class TestReceiveStock:
    async def test_creates_the_lot_appends_a_receive_and_raises_on_hand(self) -> None:
        world = World()

        balance = await receive_stock(world)(
            BENCH, Receipt(LOT_COUNTED_PART, world.drawer.id, Quantity(100))
        )

        assert int(balance.on_hand) == 100
        lot = await world.inventory.lots.for_part_at(LOT_COUNTED_PART, world.drawer.id)
        assert lot is not None
        movements = await world.inventory.ledger.movements_of(lot.id)
        assert [m.kind for m in movements] == [MovementKind.RECEIVE]
        assert movements[0].change == 100
        assert world.inventory.commits == 1

    async def test_reuses_an_existing_lot_rather_than_creating_a_second(self) -> None:
        world = World()
        lot = world.hold_lot(LOT_COUNTED_PART, world.drawer, on_hand=10)

        balance = await receive_stock(world)(
            BENCH, Receipt(LOT_COUNTED_PART, world.drawer.id, Quantity(5))
        )

        assert balance.lot_id == lot.id
        assert int(balance.on_hand) == 15
        assert len(world.inventory.lots.saved) == 1

    async def test_a_part_the_catalog_does_not_know_is_a_404(self) -> None:
        world = World()

        with pytest.raises(PartNotFoundError):
            await receive_stock(world)(
                BENCH, Receipt(PartId(uuid7()), world.drawer.id, Quantity(1))
            )

        assert world.inventory.commits == 0
        assert world.inventory.ledger.saved == []

    async def test_a_unit_tracked_part_is_refused_as_a_lot(self) -> None:
        world = World()

        with pytest.raises(ReceiveAsUnitsError, match="units"):
            await receive_stock(world)(
                BENCH, Receipt(UNIT_TRACKED_PART, world.drawer.id, Quantity(1))
            )

        assert world.inventory.commits == 0
        assert world.inventory.ledger.saved == []


class TestReceiveStockPerform:
    """The receipt inside a transaction its caller opened: it writes, the caller commits."""

    async def test_writes_the_lot_the_receive_and_the_balance_without_committing(self) -> None:
        world = World()

        async with world.inventory.for_workspace(BENCH) as work:
            balance = await receive_stock(world).perform(
                BENCH, work, Receipt(LOT_COUNTED_PART, world.drawer.id, Quantity(12))
            )

        lot = await world.inventory.lots.for_part_at(LOT_COUNTED_PART, world.drawer.id)
        assert lot is not None
        assert balance.lot_id == lot.id
        assert int(balance.on_hand) == 12
        assert await world.inventory.balances.get(lot.id) == balance
        movements = await world.inventory.ledger.movements_of(lot.id)
        assert [(m.kind, m.change) for m in movements] == [(MovementKind.RECEIVE, 12)]
        assert world.inventory.commits == 0

    async def test_leaves_the_part_check_to_its_caller(self) -> None:
        # A part the caller defined a moment earlier in its own transaction, which the
        # `Parts` port, reading in another one, doesn't know yet.
        world = World()
        new_part = PartId(uuid7())

        async with world.inventory.for_workspace(BENCH) as work:
            balance = await receive_stock(world).perform(
                BENCH, work, Receipt(new_part, world.drawer.id, Quantity(3))
            )

        assert int(balance.on_hand) == 3
        assert await world.inventory.lots.for_part_at(new_part, world.drawer.id) is not None

    async def test_a_caller_running_two_receipts_commits_once(self) -> None:
        # Two rows of one sheet can put the same part in the same place.
        world = World()
        receive = receive_stock(world)

        async with world.inventory.for_workspace(BENCH) as work:
            await receive.perform(
                BENCH, work, Receipt(LOT_COUNTED_PART, world.drawer.id, Quantity(10))
            )
            balance = await receive.perform(
                BENCH, work, Receipt(LOT_COUNTED_PART, world.drawer.id, Quantity(5))
            )
            await work.commit()

        assert int(balance.on_hand) == 15
        assert len(world.inventory.lots.saved) == 1
        movements = await world.inventory.ledger.movements_of(balance.lot_id)
        assert [m.change for m in movements] == [10, 5]
        assert world.inventory.commits == 1


class TestAdjustStock:
    async def test_sets_on_hand_to_the_counted_quantity_and_stores_the_delta(self) -> None:
        world = World()
        world.hold_lot(LOT_COUNTED_PART, world.drawer, on_hand=100)

        balance = await adjust_stock(world)(
            BENCH,
            Adjustment(LOT_COUNTED_PART, world.drawer.id, Quantity(90), MovementReason.RECOUNT),
        )

        assert int(balance.on_hand) == 90
        movements = await world.inventory.ledger.movements_of(balance.lot_id)
        assert movements[-1].kind is MovementKind.ADJUST
        assert movements[-1].change == -10
        assert movements[-1].reason is MovementReason.RECOUNT
        assert world.inventory.commits == 1

    async def test_a_count_above_the_current_stores_a_positive_delta(self) -> None:
        world = World()
        world.hold_lot(LOT_COUNTED_PART, world.drawer, on_hand=5)

        balance = await adjust_stock(world)(
            BENCH,
            Adjustment(LOT_COUNTED_PART, world.drawer.id, Quantity(8), MovementReason.FOUND),
        )

        assert int(balance.on_hand) == 8
        movements = await world.inventory.ledger.movements_of(balance.lot_id)
        assert movements[-1].change == 3

    async def test_adjusting_a_never_received_part_creates_the_lot(self) -> None:
        world = World()

        balance = await adjust_stock(world)(
            BENCH,
            Adjustment(LOT_COUNTED_PART, world.drawer.id, Quantity(7), MovementReason.CORRECTION),
        )

        assert int(balance.on_hand) == 7
        movements = await world.inventory.ledger.movements_of(balance.lot_id)
        assert movements[-1].change == 7

    async def test_a_unit_tracked_part_is_refused(self) -> None:
        world = World()

        with pytest.raises(ReceiveAsUnitsError):
            await adjust_stock(world)(
                BENCH,
                Adjustment(UNIT_TRACKED_PART, world.drawer.id, Quantity(1), MovementReason.RECOUNT),
            )

        assert world.inventory.commits == 0


class TestMoveStock:
    async def test_writes_two_grouped_rows_and_moves_the_balances(self) -> None:
        world = World()
        box = world.add_location("Parts box", world.lab)
        source = world.hold_lot(LOT_COUNTED_PART, world.drawer, on_hand=100)

        source_balance, dest_balance = await move_stock(world)(
            BENCH, Move(LOT_COUNTED_PART, world.drawer.id, box.id, Quantity(40))
        )

        assert int(source_balance.on_hand) == 60
        assert int(dest_balance.on_hand) == 40
        out_rows = await world.inventory.ledger.movements_of(source.id)
        dest_lot = await world.inventory.lots.for_part_at(LOT_COUNTED_PART, box.id)
        assert dest_lot is not None
        into_rows = await world.inventory.ledger.movements_of(dest_lot.id)
        assert out_rows[-1].kind is MovementKind.MOVE
        assert out_rows[-1].change == -40
        assert into_rows[-1].change == 40
        # The two rows share one move group, so they are one conserved pair.
        assert out_rows[-1].move_group is not None
        assert out_rows[-1].move_group == into_rows[-1].move_group
        assert world.inventory.commits == 1

    async def test_a_unit_tracked_part_is_refused(self) -> None:
        # Its units would stay pointing at the source lot while the count left it.
        world = World()
        box = world.add_location("Parts box", world.lab)
        world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=3)

        with pytest.raises(ReceiveAsUnitsError):
            await move_stock(world)(
                BENCH, Move(UNIT_TRACKED_PART, world.drawer.id, box.id, Quantity(1))
            )

        assert world.inventory.commits == 0

    async def test_creates_the_destination_lot_when_absent(self) -> None:
        world = World()
        box = world.add_location("Parts box", world.lab)
        world.hold_lot(LOT_COUNTED_PART, world.drawer, on_hand=10)

        await move_stock(world)(BENCH, Move(LOT_COUNTED_PART, world.drawer.id, box.id, Quantity(4)))

        assert await world.inventory.lots.for_part_at(LOT_COUNTED_PART, box.id) is not None

    async def test_conserves_the_total_across_locations(self) -> None:
        world = World()
        box = world.add_location("Parts box", world.lab)
        world.hold_lot(LOT_COUNTED_PART, world.drawer, on_hand=100)

        source_balance, dest_balance = await move_stock(world)(
            BENCH, Move(LOT_COUNTED_PART, world.drawer.id, box.id, Quantity(40))
        )

        assert int(source_balance.on_hand) + int(dest_balance.on_hand) == 100

    async def test_refuses_more_than_the_source_holds(self) -> None:
        world = World()
        box = world.add_location("Parts box", world.lab)
        world.hold_lot(LOT_COUNTED_PART, world.drawer, on_hand=30)

        with pytest.raises(InsufficientStockError):
            await move_stock(world)(
                BENCH, Move(LOT_COUNTED_PART, world.drawer.id, box.id, Quantity(31))
            )

        assert world.inventory.commits == 0
        assert world.inventory.ledger.saved == []

    async def test_refuses_a_source_that_holds_none_of_the_part(self) -> None:
        world = World()
        box = world.add_location("Parts box", world.lab)

        with pytest.raises(InsufficientStockError):
            await move_stock(world)(
                BENCH, Move(LOT_COUNTED_PART, world.drawer.id, box.id, Quantity(1))
            )

        assert world.inventory.commits == 0

    async def test_refuses_the_same_source_and_destination(self) -> None:
        world = World()
        world.hold_lot(LOT_COUNTED_PART, world.drawer, on_hand=10)

        with pytest.raises(SameLocationError):
            await move_stock(world)(
                BENCH, Move(LOT_COUNTED_PART, world.drawer.id, world.drawer.id, Quantity(1))
            )

        assert world.inventory.commits == 0


class TestProperties:
    @given(previous=st.integers(min_value=0, max_value=10_000), counted=st.integers(0, 10_000))
    def test_property_5_adjust_reaches_exactly_the_counted_quantity(
        self, previous: int, counted: int
    ) -> None:
        """For any lot and any counted quantity >= 0, after the adjust the lot's on_hand
        equals the counted quantity, and the stored movement's change equals
        counted - previous_on_hand.

        **Validates: Requirements 4.3, 4.4**
        """

        async def scenario() -> None:
            world = World()
            world.hold_lot(LOT_COUNTED_PART, world.drawer, on_hand=previous)

            balance = await adjust_stock(world)(
                BENCH,
                Adjustment(
                    LOT_COUNTED_PART, world.drawer.id, Quantity(counted), MovementReason.RECOUNT
                ),
            )

            assert int(balance.on_hand) == counted
            movements = await world.inventory.ledger.movements_of(balance.lot_id)
            assert movements[-1].change == counted - previous

        anyio.run(scenario)
