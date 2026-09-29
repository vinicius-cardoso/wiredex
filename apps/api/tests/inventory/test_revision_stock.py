"""`RevisionStock` reserving, releasing, consuming and returning a revision's stock over the
in-memory fakes, never committing (design decision 8).

It is inventory's half of a build transition. These tests drive it directly on the fakes — the
projects use cases and the module seam are tested in 11 and 12 — so they pin the ledger effect
of each write, the units it moves, and the four properties 6 to 9 the design lists here: units
and their lots stay consistent (6), what a revision holds follows its status (7), round trips
restore the stock (8), and reserved stock stays reserved until the build takes it (9).

The lock order and the fixed statement counts are PostgreSQL's to keep and are task 7's
integration tests; here the fakes only need to answer the same rows.
"""

from __future__ import annotations

from uuid import uuid7

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from support.identity import NewIds
from support.inventory import (
    BENCH,
    LOT_COUNTED_PART,
    UNIT_TRACKED_PART,
    World,
)
from wiredex.inventory.application.builds import LotTake, RevisionStock
from wiredex.inventory.application.ports import Adjustment
from wiredex.inventory.domain.errors import LocationNotFoundError, ReservedStockError
from wiredex.inventory.domain.lot import StockBalance
from wiredex.inventory.domain.unit import UnitStatus
from wiredex.inventory.domain.values import (
    LocationId,
    MovementKind,
    MovementReason,
    Quantity,
    RevisionId,
    StockLotId,
)

pytestmark = pytest.mark.anyio


def a_stock(world: World) -> RevisionStock:
    """`RevisionStock` over the world's fakes, its own clock and ids (never committing)."""
    return RevisionStock(world.inventory, BENCH, world.clock, NewIds())


async def on_hand_reserved(world: World, lot_id: StockLotId) -> tuple[int, int]:
    balance = world.inventory.balances.saved.get(lot_id) or StockBalance.opening(lot_id)
    return int(balance.on_hand), int(balance.reserved)


class TestReserve:
    async def test_a_reserve_writes_one_row_per_lot_and_reserves_its_units(self) -> None:
        # Two 10k lots and a named unit in the first: a reserve of both raises each lot's
        # reserved and links the unit, leaving on hand as it was (requirements 2.6, 3.1).
        world = World()
        lot_a = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=2)
        lot_b = world.hold_lot(UNIT_TRACKED_PART, world.lab, on_hand=1)
        unit_a = world.hold_unit(UNIT_TRACKED_PART, lot_a)
        unit_a2 = world.hold_unit(UNIT_TRACKED_PART, lot_a)
        unit_b = world.hold_unit(UNIT_TRACKED_PART, lot_b)
        revision = RevisionId(uuid7())
        stock = a_stock(world)

        locked = await stock.available([UNIT_TRACKED_PART], [])
        await stock.reserve(
            locked,
            revision,
            [
                LotTake(lot_a.id, 2, (unit_a.id, unit_a2.id)),
                LotTake(lot_b.id, 1, (unit_b.id,)),
            ],
        )

        assert await on_hand_reserved(world, lot_a.id) == (2, 2)
        assert await on_hand_reserved(world, lot_b.id) == (1, 1)
        reserves = [m for m in world.inventory.ledger.saved if m.kind is MovementKind.RESERVE]
        assert sorted(m.change for m in reserves) == [1, 2]
        assert all(m.revision_id == revision for m in reserves)
        for unit in (unit_a, unit_a2, unit_b):
            assert world.inventory.units.saved[unit.id].status is UnitStatus.RESERVED
            assert world.inventory.units.saved[unit.id].revision_id == revision

    async def test_available_stamps_after_the_balance_lock(self) -> None:
        world = World()
        world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=1)
        locked = await a_stock(world).available([UNIT_TRACKED_PART], [])

        assert locked.now == world.clock.now()
        assert locked.changed is False

    async def test_a_named_unit_is_locked_in_any_status(self) -> None:
        # A named unit not in stock is still locked and offered, so the caller's
        # check_named_units can refuse it; it isn't among the in-stock units (requirement 3.5).
        world = World()
        lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=1, reserved=1)
        reserved_unit = world.hold_unit(UNIT_TRACKED_PART, lot, status=UnitStatus.RESERVED)

        locked = await a_stock(world).available([UNIT_TRACKED_PART], [reserved_unit.id])

        assert reserved_unit.id in locked.named
        assert reserved_unit.id not in {unit.id for unit in locked.units}


class TestChangedRecount:
    async def test_a_matching_recount_is_not_changed(self) -> None:
        world = World()
        lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=2)
        world.hold_unit(UNIT_TRACKED_PART, lot)
        world.hold_unit(UNIT_TRACKED_PART, lot)

        locked = await a_stock(world).available([UNIT_TRACKED_PART], [])

        assert locked.changed is False

    async def test_a_piece_whose_unit_the_lock_missed_is_changed(self) -> None:
        # The balance says two on hand, but only one in-stock unit exists: a ReceiveUnits
        # landed a piece whose unit the unit lock never saw (decision 12).
        world = World()
        lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=2)
        world.hold_unit(UNIT_TRACKED_PART, lot)

        locked = await a_stock(world).available([UNIT_TRACKED_PART], [])

        assert locked.changed is True

    async def test_a_lot_counted_part_never_trips_the_recount(self) -> None:
        # A loose-lot part has no units, so its available stock isn't unit-backed and the
        # recount leaves it alone.
        world = World()
        world.hold_lot(LOT_COUNTED_PART, world.drawer, on_hand=50)

        locked = await a_stock(world).available([LOT_COUNTED_PART], [])

        assert locked.changed is False


class TestHoldings:
    async def test_holdings_fold_a_revisions_sums(self) -> None:
        world = World()
        lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=1)
        unit = world.hold_unit(UNIT_TRACKED_PART, lot)
        revision = RevisionId(uuid7())
        stock = a_stock(world)
        locked = await stock.available([UNIT_TRACKED_PART], [])
        await stock.reserve(locked, revision, [LotTake(lot.id, 1, (unit.id,))])

        held = await stock.holdings(revision)

        assert {h.lot_id: h.quantity for h in held.reserved} == {lot.id: 1}
        assert held.consumed == {}

    async def test_holdings_of_part_lists_each_holding_revision(self) -> None:
        world = World()
        lot = world.hold_lot(LOT_COUNTED_PART, world.drawer, on_hand=10)
        stock = a_stock(world)
        first, second = RevisionId(uuid7()), RevisionId(uuid7())
        for revision, qty in ((first, 3), (second, 2)):
            locked = await stock.available([LOT_COUNTED_PART], [])
            await stock.reserve(locked, revision, [LotTake(lot.id, qty, ())])

        holdings = {
            h.revision_id: h.reserved for h in await stock.holdings_of_part(LOT_COUNTED_PART)
        }

        assert holdings == {first: 3, second: 2}

    async def test_units_of_a_revision_answers_its_held_units(self) -> None:
        world = World()
        lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=1)
        unit = world.hold_unit(UNIT_TRACKED_PART, lot)
        revision = RevisionId(uuid7())
        stock = a_stock(world)
        locked = await stock.available([UNIT_TRACKED_PART], [])
        await stock.reserve(locked, revision, [LotTake(lot.id, 1, (unit.id,))])

        rows = await stock.units_of(revision)

        assert [row.unit.id for row in rows] == [unit.id]
        assert rows[0].location_code == str(world.drawer.code)


class TestCancelAndBuild:
    async def test_cancel_releases_every_lot_and_frees_the_units(self) -> None:
        world = World()
        lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=2)
        unit = world.hold_unit(UNIT_TRACKED_PART, lot)
        revision = RevisionId(uuid7())
        stock = a_stock(world)
        locked = await stock.available([UNIT_TRACKED_PART], [])
        await stock.reserve(locked, revision, [LotTake(lot.id, 1, (unit.id,))])

        await stock.release(revision)

        assert await on_hand_reserved(world, lot.id) == (2, 0)
        assert world.inventory.units.saved[unit.id].status is UnitStatus.IN_STOCK
        assert world.inventory.units.saved[unit.id].revision_id is None
        assert (await stock.holdings(revision)).reserved == ()

    async def test_build_consumes_every_lot_and_marks_units_in_use(self) -> None:
        world = World()
        lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=2)
        unit = world.hold_unit(UNIT_TRACKED_PART, lot)
        revision = RevisionId(uuid7())
        stock = a_stock(world)
        locked = await stock.available([UNIT_TRACKED_PART], [])
        await stock.reserve(locked, revision, [LotTake(lot.id, 1, (unit.id,))])

        await stock.consume(revision)

        assert await on_hand_reserved(world, lot.id) == (1, 0)
        built = world.inventory.units.saved[unit.id]
        assert built.status is UnitStatus.IN_USE
        assert built.revision_id == revision  # the link is kept (requirement 3.6)
        assert (await stock.holdings(revision)).consumed == {UNIT_TRACKED_PART: 1}


class TestDismantle:
    async def test_dismantle_returns_to_the_chosen_location_and_frees_the_units(self) -> None:
        world = World()
        lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=2)
        unit = world.hold_unit(UNIT_TRACKED_PART, lot)
        revision = RevisionId(uuid7())
        stock = a_stock(world)
        locked = await stock.available([UNIT_TRACKED_PART], [])
        await stock.reserve(locked, revision, [LotTake(lot.id, 1, (unit.id,))])
        await stock.consume(revision)

        # Return into the Lab, not the drawer it came from: a breadboard lands in one tray.
        await stock.return_to(revision, world.lab.id)

        return_lot = await world.inventory.lots.for_part_at(UNIT_TRACKED_PART, world.lab.id)
        assert return_lot is not None
        assert await on_hand_reserved(world, return_lot.id) == (1, 0)
        returned = world.inventory.units.saved[unit.id]
        assert returned.status is UnitStatus.IN_STOCK
        assert returned.revision_id is None
        assert returned.lot_id == return_lot.id
        assert (await stock.holdings(revision)).consumed == {}

    async def test_dismantle_refuses_a_location_the_workspace_doesnt_hold(self) -> None:
        world = World()
        lot = world.hold_lot(LOT_COUNTED_PART, world.drawer, on_hand=5)
        revision = RevisionId(uuid7())
        stock = a_stock(world)
        locked = await stock.available([LOT_COUNTED_PART], [])
        await stock.reserve(locked, revision, [LotTake(lot.id, 2, ())])
        await stock.consume(revision)

        with pytest.raises(LocationNotFoundError):
            await stock.return_to(revision, LocationId(uuid7()))


# --- Properties 6 to 9 -----------------------------------------------------------------------


async def _lot_units_consistent(world: World) -> None:
    """Property 6's invariant: for every lot whose stock came in as units, on hand is its
    in-stock plus reserved units, and reserved is its reserved units."""
    for lot_id in world.inventory.lots.saved:
        units = [u for u in world.inventory.units.saved.values() if u.lot_id == lot_id]
        if not units:
            continue
        in_stock = sum(1 for u in units if u.status is UnitStatus.IN_STOCK)
        reserved_units = sum(1 for u in units if u.status is UnitStatus.RESERVED)
        on_hand, reserved = await on_hand_reserved(world, lot_id)
        assert on_hand == in_stock + reserved_units
        assert reserved == reserved_units


class TestProperty6:
    @given(
        quantity=st.integers(min_value=1, max_value=6), take=st.integers(min_value=1, max_value=6)
    )
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_units_and_their_lots_stay_consistent(self, quantity: int, take: int) -> None:
        """For a reserve, then a cancel or a build and its dismantle, every lot whose stock
        came in as units keeps its on hand equal to its in-stock plus reserved units and its
        reserved equal to its reserved units.

        **Validates: Requirements 3.9**
        """
        world = World()
        lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=quantity)
        units = [world.hold_unit(UNIT_TRACKED_PART, lot) for _ in range(quantity)]
        take = min(take, quantity)
        revision = RevisionId(uuid7())
        stock = a_stock(world)

        locked = await stock.available([UNIT_TRACKED_PART], [])
        chosen = tuple(u.id for u in units[:take])
        await stock.reserve(locked, revision, [LotTake(lot.id, take, chosen)])
        await _lot_units_consistent(world)

        # Build then dismantle back into the same drawer; the invariant holds throughout.
        await stock.consume(revision)
        await _lot_units_consistent(world)
        await stock.return_to(revision, world.drawer.id)
        await _lot_units_consistent(world)


class TestProperty7:
    @given(
        walk=st.lists(
            st.sampled_from(["reserve", "cancel", "build", "dismantle"]),
            min_size=0,
            max_size=6,
        )
    )
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_holdings_follow_the_status_and_a_fork_holds_nothing(
        self, walk: list[str]
    ) -> None:
        """Over any legal walk of the lifecycle from draft, a revision's holdings are empty
        while draft or dismantled, its reservation per lot while reserved, and its consumption
        per part while built; a fresh revision id, as a fork's is, holds nothing.

        **Validates: Requirements 8.5, 8.6, 9.4**
        """
        world = World()
        lot = world.hold_lot(LOT_COUNTED_PART, world.drawer, on_hand=10)
        revision = RevisionId(uuid7())
        stock = a_stock(world)
        need = 3
        walker = _Walk(stock, world, revision, lot.id, need)
        status = "draft"

        for step in walk:
            status = await walker.apply(status, step)

        held = await stock.holdings(revision)
        if status == "reserved":
            assert {h.lot_id: h.quantity for h in held.reserved} == {lot.id: need}
            assert held.consumed == {}
        elif status == "built":
            assert held.reserved == ()
            assert held.consumed == {LOT_COUNTED_PART: need}
        else:  # draft or dismantled
            assert held.reserved == ()
            assert held.consumed == {}

        # A fork's id has no movements, so it holds nothing whatever its source holds.
        fork = await stock.holdings(RevisionId(uuid7()))
        assert fork.reserved == ()
        assert fork.consumed == {}


class TestProperty8:
    @given(
        quantity=st.integers(min_value=1, max_value=8), take=st.integers(min_value=1, max_value=8)
    )
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_round_trips_restore_the_stock(self, quantity: int, take: int) -> None:
        """Reserving then cancelling leaves every lot's on hand and reserved as they started;
        building then dismantling to a location leaves each part's total on hand as it was,
        everything the build consumed on hand there.

        **Validates: Requirements 4.2, 4.3, 6.3**
        """
        world = World()
        lot = world.hold_lot(LOT_COUNTED_PART, world.drawer, on_hand=quantity)
        take = min(take, quantity)
        stock = a_stock(world)

        reserve_cancel = RevisionId(uuid7())
        locked = await stock.available([LOT_COUNTED_PART], [])
        await stock.reserve(locked, reserve_cancel, [LotTake(lot.id, take, ())])
        await stock.release(reserve_cancel)
        assert await on_hand_reserved(world, lot.id) == (quantity, 0)

        # A reserve after the cancel reads the stock as it then stands (requirement 4.3).
        build_dismantle = RevisionId(uuid7())
        locked = await stock.available([LOT_COUNTED_PART], [])
        await stock.reserve(locked, build_dismantle, [LotTake(lot.id, take, ())])
        await stock.consume(build_dismantle)
        await stock.return_to(build_dismantle, world.lab.id)

        return_lot = await world.inventory.lots.for_part_at(LOT_COUNTED_PART, world.lab.id)
        assert return_lot is not None
        drawer_on_hand, _ = await on_hand_reserved(world, lot.id)
        lab_on_hand, _ = await on_hand_reserved(world, return_lot.id)
        # Each part's total on hand is back to what it was, with the returned pieces at the Lab.
        assert drawer_on_hand + lab_on_hand == quantity
        assert lab_on_hand == take


class TestProperty9:
    @given(
        quantity=st.integers(min_value=2, max_value=10),
        take=st.integers(min_value=1, max_value=9),
        recount=st.integers(min_value=0, max_value=12),
    )
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_reserved_stock_stays_reserved_until_the_build_takes_it(
        self, quantity: int, take: int, recount: int
    ) -> None:
        """A recount below a lot's reserved is refused with `ReservedStockError`; the build
        then writes one `CONSUME` per lot of exactly the quantity reserved there and never
        fails for want of stock.

        **Validates: Requirements 5.2, 7.1, 7.2**
        """
        world = World()
        take = min(take, quantity)
        lot = world.hold_lot(LOT_COUNTED_PART, world.drawer, on_hand=quantity)
        revision = RevisionId(uuid7())
        stock = a_stock(world)
        locked = await stock.available([LOT_COUNTED_PART], [])
        await stock.reserve(locked, revision, [LotTake(lot.id, take, ())])

        # A recount to `recount`: below the reserved `take` it is refused; at or above it holds.
        _, reserved = await on_hand_reserved(world, lot.id)
        if recount < reserved:
            with pytest.raises(ReservedStockError):
                await world.adjust_stock(BENCH, _recount(world, lot.id, recount))
            _, still = await on_hand_reserved(world, lot.id)
            assert still == reserved
        else:
            await world.adjust_stock(BENCH, _recount(world, lot.id, recount))
            _, still = await on_hand_reserved(world, lot.id)
            assert still == reserved

        before, _ = await on_hand_reserved(world, lot.id)
        await stock.consume(revision)
        after, after_reserved = await on_hand_reserved(world, lot.id)
        consumes = [m for m in world.inventory.ledger.saved if m.kind is MovementKind.CONSUME]
        assert [m.change for m in consumes] == [-take]
        assert after == before - take
        assert after_reserved == 0


class _Walk:
    """Applies a lifecycle walk to one revision's stock, skipping a step its status doesn't
    allow — the guard the projects use cases put on the transition, here so a random walk only
    ever asks RevisionStock for a move its status allows (property 7)."""

    def __init__(
        self,
        stock: RevisionStock,
        world: World,
        revision: RevisionId,
        lot_id: StockLotId,
        need: int,
    ) -> None:
        self._stock = stock
        self._world = world
        self._revision = revision
        self._lot_id = lot_id
        self._need = need

    async def apply(self, status: str, step: str) -> str:
        if step == "reserve" and status == "draft":
            locked = await self._stock.available([LOT_COUNTED_PART], [])
            take = [LotTake(self._lot_id, self._need, ())]
            await self._stock.reserve(locked, self._revision, take)
            return "reserved"
        if step == "cancel" and status == "reserved":
            await self._stock.release(self._revision)
            return "draft"
        if step == "build" and status == "reserved":
            await self._stock.consume(self._revision)
            return "built"
        if step == "dismantle" and status == "built":
            await self._stock.return_to(self._revision, self._world.drawer.id)
            return "dismantled"
        return status


def _recount(world: World, lot_id: StockLotId, counted: int) -> Adjustment:
    lot = world.inventory.lots.saved[lot_id]
    location = world.inventory.locations.saved[lot.location_id]
    return Adjustment(
        part_id=lot.part_id,
        location_id=location.id,
        counted=Quantity(counted),
        reason=MovementReason.RECOUNT,
    )
