"""The unit use cases over the in-memory fakes.

`ReceiveUnits` (task 4): receiving N units of a unit-tracked part writes the ordinary lot +
`RECEIVE` + balance and creates N units with consecutive `WX-U-NNNN` codes, in one transaction
— the mirror of the lot `ReceiveStock`. A lot-counted part is refused (`ReceiveAsLotError`), a
part the catalog doesn't know is a 404, and a duplicate serial (per part) or MAC (per
workspace) is refused before a single row is written. Property 1 pins the invariant (a lot's
on_hand equals its in_stock units) and property 4 the codes (distinct, consecutive).

`RelabelUnit`, `RetireUnit`, `UnretireUnit`, `MoveUnit`, `DeleteUnit` (task 5): relabel refuses
a duplicate and commits nothing when unchanged; retire and un-retire write the compensating
`ADJUST ∓1`; move delegates to the two-row `MOVE` and refuses the same location and a retired
unit; delete is refused unless the unit is retired. Property 2 pins that a move conserves
units and count, property 3 that retire↔un-retire is stock-neutral.

`ListUnitsOfPart`, `ListUnitsOfLocation`, `SearchUnits` (task 6): the part's units, the units
sitting in a location (across every lot there, never another location's or part's), and the
workspace search matching a code, serial or MAC as a case-insensitive substring. Reads: they
open the caller's workspace and never commit.
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
from wiredex.inventory.application.units import (
    NewUnit,
    ReceiveUnits,
    UnitReceipt,
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
from wiredex.inventory.domain.unit import UnitStatus
from wiredex.inventory.domain.values import (
    Mac,
    MovementKind,
    MovementReason,
    PartId,
    Serial,
    UnitId,
)

pytestmark = pytest.mark.anyio


def receive_units(world: World) -> ReceiveUnits:
    return ReceiveUnits(world.inventory.for_workspace, world.parts, world.clock, world.ids)


def blank_units(count: int) -> tuple[NewUnit, ...]:
    """`count` units with neither serial nor MAC — any number may be left blank (5.5)."""
    return tuple(NewUnit() for _ in range(count))


class TestReceiveUnits:
    async def test_creates_n_units_with_consecutive_codes_and_raises_on_hand(self) -> None:
        world = World()

        received = await receive_units(world)(
            BENCH, UnitReceipt(UNIT_TRACKED_PART, world.drawer.id, blank_units(3))
        )

        assert int(received.balance.on_hand) == 3
        assert [str(u.code) for u in received.units] == ["WX-U-0001", "WX-U-0002", "WX-U-0003"]
        assert len(world.inventory.units.saved) == 3
        assert all(u.status is UnitStatus.IN_STOCK for u in received.units)
        assert world.inventory.commits == 1

    async def test_records_one_receive_of_n_on_the_lot(self) -> None:
        world = World()

        received = await receive_units(world)(
            BENCH, UnitReceipt(UNIT_TRACKED_PART, world.drawer.id, blank_units(4))
        )

        movements = await world.inventory.ledger.movements_of(received.balance.lot_id)
        assert [m.kind for m in movements] == [MovementKind.RECEIVE]
        assert movements[0].change == 4

    async def test_every_unit_points_at_the_lot(self) -> None:
        world = World()

        received = await receive_units(world)(
            BENCH, UnitReceipt(UNIT_TRACKED_PART, world.drawer.id, blank_units(2))
        )

        assert {u.lot_id for u in received.units} == {received.balance.lot_id}
        lot = await world.inventory.lots.for_part_at(UNIT_TRACKED_PART, world.drawer.id)
        assert lot is not None
        assert received.balance.lot_id == lot.id

    async def test_receiving_into_an_existing_lot_reuses_it_and_adds_to_on_hand(self) -> None:
        world = World()
        # One unit already received into the lot: on_hand of 1, one in_stock unit.
        lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=1)
        world.hold_unit(UNIT_TRACKED_PART, lot)

        received = await receive_units(world)(
            BENCH, UnitReceipt(UNIT_TRACKED_PART, world.drawer.id, blank_units(2))
        )

        assert received.balance.lot_id == lot.id
        assert int(received.balance.on_hand) == 3
        assert len(world.inventory.lots.saved) == 1
        assert await world.inventory.units.in_stock_at(lot.id) == 3

    async def test_applies_the_per_unit_serial_and_mac(self) -> None:
        world = World()

        received = await receive_units(world)(
            BENCH,
            UnitReceipt(
                UNIT_TRACKED_PART,
                world.drawer.id,
                (
                    NewUnit(serial=Serial("SN-1"), mac=Mac("AA-BB-CC-DD-EE-FF")),
                    NewUnit(serial=Serial("SN-2")),
                    NewUnit(),
                ),
            ),
        )

        first, second, third = received.units
        assert first.serial == Serial("SN-1")
        assert str(first.mac) == "aa:bb:cc:dd:ee:ff"
        assert second.serial == Serial("SN-2")
        assert second.mac is None
        assert third.serial is None
        assert third.mac is None

    async def test_a_part_the_catalog_does_not_know_is_a_404(self) -> None:
        world = World()

        with pytest.raises(PartNotFoundError):
            await receive_units(world)(
                BENCH, UnitReceipt(PartId(uuid7()), world.drawer.id, blank_units(1))
            )

        assert world.inventory.commits == 0
        assert world.inventory.ledger.saved == []
        assert world.inventory.units.saved == {}

    async def test_a_lot_counted_part_is_refused_as_units(self) -> None:
        world = World()

        with pytest.raises(ReceiveAsLotError, match="lots"):
            await receive_units(world)(
                BENCH, UnitReceipt(LOT_COUNTED_PART, world.drawer.id, blank_units(1))
            )

        assert world.inventory.commits == 0
        assert world.inventory.ledger.saved == []
        assert world.inventory.units.saved == {}

    async def test_a_serial_another_unit_of_the_part_holds_is_refused_before_any_write(
        self,
    ) -> None:
        world = World()
        lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=1)
        world.hold_unit(UNIT_TRACKED_PART, lot, serial=Serial("SN-42"))

        # A different case still collides: the per-part index folds case (requirement 5.1).
        with pytest.raises(DuplicateSerialError):
            await receive_units(world)(
                BENCH,
                UnitReceipt(UNIT_TRACKED_PART, world.drawer.id, (NewUnit(serial=Serial("sn-42")),)),
            )

        assert world.inventory.commits == 0
        assert world.inventory.ledger.saved == []
        assert len(world.inventory.units.saved) == 1

    async def test_a_mac_another_unit_in_the_workspace_holds_is_refused_before_any_write(
        self,
    ) -> None:
        world = World()
        lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=1)
        world.hold_unit(UNIT_TRACKED_PART, lot, mac=Mac("aa:bb:cc:dd:ee:ff"))

        # A different spelling of the same address collides: the stored value is canonical.
        with pytest.raises(DuplicateMacError):
            await receive_units(world)(
                BENCH,
                UnitReceipt(
                    UNIT_TRACKED_PART, world.drawer.id, (NewUnit(mac=Mac("AA-BB-CC-DD-EE-FF")),)
                ),
            )

        assert world.inventory.commits == 0
        assert world.inventory.ledger.saved == []
        assert len(world.inventory.units.saved) == 1

    async def test_a_serial_repeated_within_the_receipt_is_refused(self) -> None:
        world = World()

        with pytest.raises(DuplicateSerialError):
            await receive_units(world)(
                BENCH,
                UnitReceipt(
                    UNIT_TRACKED_PART,
                    world.drawer.id,
                    (NewUnit(serial=Serial("SN-1")), NewUnit(serial=Serial("sn-1"))),
                ),
            )

        assert world.inventory.commits == 0
        assert world.inventory.units.saved == {}

    async def test_a_mac_repeated_within_the_receipt_is_refused(self) -> None:
        world = World()

        with pytest.raises(DuplicateMacError):
            await receive_units(world)(
                BENCH,
                UnitReceipt(
                    UNIT_TRACKED_PART,
                    world.drawer.id,
                    (NewUnit(mac=Mac("aa:bb:cc:dd:ee:ff")), NewUnit(mac=Mac("AA-BB-CC-DD-EE-FF"))),
                ),
            )

        assert world.inventory.commits == 0
        assert world.inventory.units.saved == {}

    async def test_scopes_the_receipt_to_the_callers_workspace(self) -> None:
        world = World()

        await receive_units(world)(
            BENCH, UnitReceipt(UNIT_TRACKED_PART, world.drawer.id, blank_units(1))
        )

        assert world.inventory.opened_for == [BENCH]


class TestReceiveUnitsPerform:
    """The receipt inside a transaction its caller opened: it writes, the caller commits."""

    async def test_writes_the_lot_the_receive_and_the_units_without_committing(self) -> None:
        world = World()

        async with world.inventory.for_workspace(BENCH) as work:
            received = await receive_units(world).perform(
                BENCH,
                work,
                UnitReceipt(
                    UNIT_TRACKED_PART, world.drawer.id, (NewUnit(serial=Serial("SN-1")), NewUnit())
                ),
            )

        lot_id = received.balance.lot_id
        assert int(received.balance.on_hand) == 2
        assert await world.inventory.balances.get(lot_id) == received.balance
        movements = await world.inventory.ledger.movements_of(lot_id)
        assert [(m.kind, m.change) for m in movements] == [(MovementKind.RECEIVE, 2)]
        assert [str(u.code) for u in received.units] == ["WX-U-0001", "WX-U-0002"]
        assert received.units[0].serial == Serial("SN-1")
        assert await world.inventory.units.in_stock_at(lot_id) == 2
        assert world.inventory.commits == 0

    async def test_leaves_the_part_check_to_its_caller(self) -> None:
        # A part the caller defined a moment earlier in its own transaction, which the
        # `Parts` port, reading in another one, doesn't know yet.
        world = World()
        new_part = PartId(uuid7())

        async with world.inventory.for_workspace(BENCH) as work:
            received = await receive_units(world).perform(
                BENCH, work, UnitReceipt(new_part, world.drawer.id, blank_units(1))
            )

        assert [u.part_id for u in received.units] == [new_part]

    async def test_still_refuses_a_duplicate_before_writing(self) -> None:
        world = World()
        lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=1)
        world.hold_unit(UNIT_TRACKED_PART, lot, mac=Mac("aa:bb:cc:dd:ee:ff"))

        async with world.inventory.for_workspace(BENCH) as work:
            with pytest.raises(DuplicateMacError):
                await receive_units(world).perform(
                    BENCH,
                    work,
                    UnitReceipt(
                        UNIT_TRACKED_PART,
                        world.drawer.id,
                        (NewUnit(mac=Mac("AA-BB-CC-DD-EE-FF")),),
                    ),
                )

        assert world.inventory.ledger.saved == []
        assert len(world.inventory.units.saved) == 1

    async def test_a_caller_running_two_receipts_commits_once(self) -> None:
        world = World()
        box = world.add_location("Parts box", world.lab)
        receive = receive_units(world)

        async with world.inventory.for_workspace(BENCH) as work:
            first = await receive.perform(
                BENCH, work, UnitReceipt(UNIT_TRACKED_PART, world.drawer.id, blank_units(2))
            )
            second = await receive.perform(
                BENCH, work, UnitReceipt(UNIT_TRACKED_PART, box.id, blank_units(1))
            )
            await work.commit()

        # The codes run on across the two receipts, and each lot counts its own units.
        codes = [str(u.code) for u in (*first.units, *second.units)]
        assert codes == ["WX-U-0001", "WX-U-0002", "WX-U-0003"]
        for received in (first, second):
            lot_id = received.balance.lot_id
            assert int(received.balance.on_hand) == await world.inventory.units.in_stock_at(lot_id)
        assert world.inventory.commits == 1


class TestProperties:
    @given(quantity=st.integers(min_value=1, max_value=25))
    def test_property_1_on_hand_equals_in_stock_units(self, quantity: int) -> None:
        """For a receipt of N units of a unit-tracked part, the lot's on_hand equals the
        number of its in_stock units.

        **Validates: Requirements 1.4, 3.3, 3.4**
        """

        async def scenario() -> None:
            world = World()
            received = await receive_units(world)(
                BENCH, UnitReceipt(UNIT_TRACKED_PART, world.drawer.id, blank_units(quantity))
            )
            lot_id = received.balance.lot_id
            in_stock = await world.inventory.units.in_stock_at(lot_id)
            assert int(received.balance.on_hand) == in_stock == quantity

        anyio.run(scenario)

    @given(quantity=st.integers(min_value=1, max_value=25))
    def test_property_4_codes_are_distinct_and_consecutive(self, quantity: int) -> None:
        """For a receipt of N units, the N codes are distinct, consecutive, and of the form
        WX-U-NNNN, no code handed to two units.

        **Validates: Requirements 2.1, 2.2**
        """

        async def scenario() -> None:
            world = World()
            received = await receive_units(world)(
                BENCH, UnitReceipt(UNIT_TRACKED_PART, world.drawer.id, blank_units(quantity))
            )
            codes = [str(u.code) for u in received.units]
            assert len(set(codes)) == quantity
            numbers = [int(code.removeprefix("WX-U-")) for code in codes]
            assert numbers == list(range(numbers[0], numbers[0] + quantity))

        anyio.run(scenario)

    @given(quantity=st.integers(min_value=1, max_value=15))
    def test_property_2_a_move_conserves_units_and_count(self, quantity: int) -> None:
        """Moving one unit keeps the same set of units and the same total on_hand for the
        part; only the moved unit's lot_id and the two lots' balances change, by ∓1, staying
        in agreement.

        **Validates: Requirements 4.2, 4.3**
        """

        async def scenario() -> None:
            world = World()
            box = world.add_location("Parts box", world.lab)
            received = await receive_units(world)(
                BENCH, UnitReceipt(UNIT_TRACKED_PART, world.drawer.id, blank_units(quantity))
            )
            source_lot_id = received.balance.lot_id
            before = set(world.inventory.units.saved)
            unit = received.units[0]

            moved = await world.move_unit(BENCH, unit.id, box.id)

            # The same set of units, only the moved one repointed.
            assert set(world.inventory.units.saved) == before
            dest_lot = await world.inventory.lots.for_part_at(UNIT_TRACKED_PART, box.id)
            assert dest_lot is not None
            assert moved.lot_id == dest_lot.id
            source_balance = await world.inventory.balances.get(source_lot_id)
            dest_balance = await world.inventory.balances.get(dest_lot.id)
            assert source_balance is not None
            assert dest_balance is not None
            # Total conserved; each balance agrees with its in-stock unit count (property 1).
            assert int(source_balance.on_hand) + int(dest_balance.on_hand) == quantity
            assert int(source_balance.on_hand) == quantity - 1
            assert int(dest_balance.on_hand) == 1
            assert await world.inventory.units.in_stock_at(source_lot_id) == quantity - 1
            assert await world.inventory.units.in_stock_at(dest_lot.id) == 1

        anyio.run(scenario)

    @given(quantity=st.integers(min_value=1, max_value=15))
    def test_property_3_retire_then_unretire_is_stock_neutral(self, quantity: int) -> None:
        """Retiring an in_stock unit then un-retiring it returns the lot's on_hand to its
        starting value and the unit to in_stock, and the ledger holds the two compensating
        movements (-1 then +1).

        **Validates: Requirements 3.1, 3.2, 3.5**
        """

        async def scenario() -> None:
            world = World()
            received = await receive_units(world)(
                BENCH, UnitReceipt(UNIT_TRACKED_PART, world.drawer.id, blank_units(quantity))
            )
            lot_id = received.balance.lot_id
            unit = received.units[0]

            await world.retire_unit(BENCH, unit.id)
            after_retire = await world.inventory.balances.get(lot_id)
            assert after_retire is not None
            assert int(after_retire.on_hand) == quantity - 1

            unretired = await world.unretire_unit(BENCH, unit.id)

            assert unretired.status is UnitStatus.IN_STOCK
            after = await world.inventory.balances.get(lot_id)
            assert after is not None
            assert int(after.on_hand) == quantity
            assert await world.inventory.units.in_stock_at(lot_id) == quantity
            # The two compensating movements sit after the RECEIVE: -1 then +1.
            adjusts = [
                m.change
                for m in await world.inventory.ledger.movements_of(lot_id)
                if m.kind is MovementKind.ADJUST
            ]
            assert adjusts == [-1, 1]

        anyio.run(scenario)


class TestRelabelUnit:
    async def test_sets_the_serial_and_mac_and_commits(self) -> None:
        world = World()
        lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=1)
        unit = world.hold_unit(UNIT_TRACKED_PART, lot)

        relabelled = await world.relabel_unit(
            BENCH, unit.id, Serial("SN-9"), Mac("AA-BB-CC-DD-EE-FF")
        )

        assert relabelled.serial == Serial("SN-9")
        assert str(relabelled.mac) == "aa:bb:cc:dd:ee:ff"
        assert world.inventory.commits == 1

    async def test_a_missing_unit_is_a_404(self) -> None:
        world = World()

        with pytest.raises(UnitNotFoundError):
            await world.relabel_unit(BENCH, UnitId(uuid7()), Serial("SN-1"), None)

        assert world.inventory.commits == 0

    async def test_an_unchanged_relabel_commits_nothing(self) -> None:
        world = World()
        lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=1)
        unit = world.hold_unit(
            UNIT_TRACKED_PART, lot, serial=Serial("SN-1"), mac=Mac("aa:bb:cc:dd:ee:ff")
        )

        await world.relabel_unit(BENCH, unit.id, Serial("SN-1"), Mac("aa:bb:cc:dd:ee:ff"))

        assert world.inventory.commits == 0

    async def test_a_serial_another_unit_of_the_part_holds_is_refused(self) -> None:
        world = World()
        lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=2)
        world.hold_unit(UNIT_TRACKED_PART, lot, serial=Serial("SN-42"))
        target = world.hold_unit(UNIT_TRACKED_PART, lot)

        # A different case still collides: the per-part index folds case (requirement 5.1).
        with pytest.raises(DuplicateSerialError):
            await world.relabel_unit(BENCH, target.id, Serial("sn-42"), None)

        assert world.inventory.commits == 0

    async def test_a_mac_another_unit_in_the_workspace_holds_is_refused(self) -> None:
        world = World()
        lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=2)
        world.hold_unit(UNIT_TRACKED_PART, lot, mac=Mac("aa:bb:cc:dd:ee:ff"))
        target = world.hold_unit(UNIT_TRACKED_PART, lot)

        with pytest.raises(DuplicateMacError):
            await world.relabel_unit(BENCH, target.id, None, Mac("AA-BB-CC-DD-EE-FF"))

        assert world.inventory.commits == 0

    async def test_keeping_its_own_serial_is_not_a_duplicate(self) -> None:
        world = World()
        lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=1)
        unit = world.hold_unit(UNIT_TRACKED_PART, lot, serial=Serial("SN-1"))

        # The unit's own serial never counts against it: only the MAC changes here.
        relabelled = await world.relabel_unit(
            BENCH, unit.id, Serial("SN-1"), Mac("aa:bb:cc:dd:ee:ff")
        )

        assert relabelled.serial == Serial("SN-1")
        assert str(relabelled.mac) == "aa:bb:cc:dd:ee:ff"
        assert world.inventory.commits == 1

    async def test_clearing_the_serial_and_mac_is_allowed(self) -> None:
        world = World()
        lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=1)
        unit = world.hold_unit(
            UNIT_TRACKED_PART, lot, serial=Serial("SN-1"), mac=Mac("aa:bb:cc:dd:ee:ff")
        )

        relabelled = await world.relabel_unit(BENCH, unit.id, None, None)

        assert relabelled.serial is None
        assert relabelled.mac is None
        assert world.inventory.commits == 1


class TestRetireUnit:
    async def test_retires_and_writes_a_compensating_adjust_of_minus_one(self) -> None:
        world = World()
        lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=1)
        unit = world.hold_unit(UNIT_TRACKED_PART, lot)

        retired = await world.retire_unit(BENCH, unit.id)

        assert retired.status is UnitStatus.RETIRED
        movements = await world.inventory.ledger.movements_of(lot.id)
        assert [m.kind for m in movements] == [MovementKind.ADJUST]
        assert movements[0].change == -1
        assert movements[0].reason is MovementReason.DAMAGED
        balance = await world.inventory.balances.get(lot.id)
        assert balance is not None
        assert int(balance.on_hand) == 0
        assert await world.inventory.units.in_stock_at(lot.id) == 0
        assert world.inventory.commits == 1

    async def test_the_reason_can_be_lost(self) -> None:
        world = World()
        lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=1)
        unit = world.hold_unit(UNIT_TRACKED_PART, lot)

        await world.retire_unit(BENCH, unit.id, MovementReason.LOST)

        movements = await world.inventory.ledger.movements_of(lot.id)
        assert movements[0].reason is MovementReason.LOST

    async def test_a_missing_unit_is_a_404(self) -> None:
        world = World()

        with pytest.raises(UnitNotFoundError):
            await world.retire_unit(BENCH, UnitId(uuid7()))

        assert world.inventory.commits == 0

    async def test_retiring_an_already_retired_unit_commits_nothing(self) -> None:
        world = World()
        lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=0)
        unit = world.hold_unit(UNIT_TRACKED_PART, lot, status=UnitStatus.RETIRED)

        retired = await world.retire_unit(BENCH, unit.id)

        assert retired.status is UnitStatus.RETIRED
        assert world.inventory.ledger.saved == []
        assert world.inventory.commits == 0


class TestUnretireUnit:
    async def test_unretires_and_writes_a_compensating_adjust_of_plus_one(self) -> None:
        world = World()
        lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=0)
        unit = world.hold_unit(UNIT_TRACKED_PART, lot, status=UnitStatus.RETIRED)

        unretired = await world.unretire_unit(BENCH, unit.id)

        assert unretired.status is UnitStatus.IN_STOCK
        movements = await world.inventory.ledger.movements_of(lot.id)
        assert [m.kind for m in movements] == [MovementKind.ADJUST]
        assert movements[0].change == 1
        assert movements[0].reason is MovementReason.FOUND
        balance = await world.inventory.balances.get(lot.id)
        assert balance is not None
        assert int(balance.on_hand) == 1
        assert await world.inventory.units.in_stock_at(lot.id) == 1
        assert world.inventory.commits == 1

    async def test_unretiring_an_in_stock_unit_commits_nothing(self) -> None:
        world = World()
        lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=1)
        unit = world.hold_unit(UNIT_TRACKED_PART, lot)

        await world.unretire_unit(BENCH, unit.id)

        assert world.inventory.ledger.saved == []
        assert world.inventory.commits == 0


class TestMoveUnit:
    async def test_delegates_to_the_two_row_move_and_repoints_the_unit(self) -> None:
        world = World()
        box = world.add_location("Parts box", world.lab)
        lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=1)
        unit = world.hold_unit(UNIT_TRACKED_PART, lot)

        moved = await world.move_unit(BENCH, unit.id, box.id)

        dest_lot = await world.inventory.lots.for_part_at(UNIT_TRACKED_PART, box.id)
        assert dest_lot is not None
        assert moved.lot_id == dest_lot.id
        out_rows = await world.inventory.ledger.movements_of(lot.id)
        into_rows = await world.inventory.ledger.movements_of(dest_lot.id)
        assert out_rows[-1].kind is MovementKind.MOVE
        assert out_rows[-1].change == -1
        assert into_rows[-1].change == 1
        assert out_rows[-1].move_group == into_rows[-1].move_group
        source_balance = await world.inventory.balances.get(lot.id)
        dest_balance = await world.inventory.balances.get(dest_lot.id)
        assert source_balance is not None
        assert int(source_balance.on_hand) == 0
        assert dest_balance is not None
        assert int(dest_balance.on_hand) == 1
        assert world.inventory.commits == 1

    async def test_conserves_the_parts_total_across_the_two_lots(self) -> None:
        world = World()
        box = world.add_location("Parts box", world.lab)
        lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=1)
        unit = world.hold_unit(UNIT_TRACKED_PART, lot)

        moved = await world.move_unit(BENCH, unit.id, box.id)

        source_balance = await world.inventory.balances.get(lot.id)
        dest_balance = await world.inventory.balances.get(moved.lot_id)
        assert source_balance is not None
        assert dest_balance is not None
        assert int(source_balance.on_hand) + int(dest_balance.on_hand) == 1

    async def test_a_missing_unit_is_a_404(self) -> None:
        world = World()
        box = world.add_location("Parts box", world.lab)

        with pytest.raises(UnitNotFoundError):
            await world.move_unit(BENCH, UnitId(uuid7()), box.id)

        assert world.inventory.commits == 0

    async def test_moving_to_the_same_location_is_refused(self) -> None:
        world = World()
        lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=1)
        unit = world.hold_unit(UNIT_TRACKED_PART, lot)

        with pytest.raises(SameLocationError):
            await world.move_unit(BENCH, unit.id, world.drawer.id)

        assert world.inventory.commits == 0

    async def test_moving_a_retired_unit_is_refused(self) -> None:
        world = World()
        box = world.add_location("Parts box", world.lab)
        lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=0)
        unit = world.hold_unit(UNIT_TRACKED_PART, lot, status=UnitStatus.RETIRED)

        with pytest.raises(InventoryError, match="retired"):
            await world.move_unit(BENCH, unit.id, box.id)

        assert world.inventory.commits == 0
        assert world.inventory.ledger.saved == []


class TestDeleteUnit:
    async def test_removes_a_retired_unit_and_leaves_the_ledger(self) -> None:
        world = World()
        lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=1)
        unit = world.hold_unit(UNIT_TRACKED_PART, lot)
        # Retire it first, so a compensating ADJUST sits on the lot; deleting must leave it.
        await world.retire_unit(BENCH, unit.id)

        await world.delete_unit(BENCH, unit.id)

        assert await world.inventory.units.get(unit.id) is None
        movements = await world.inventory.ledger.movements_of(lot.id)
        assert [m.kind for m in movements] == [MovementKind.ADJUST]
        assert movements[0].change == -1

    async def test_an_in_stock_unit_is_refused(self) -> None:
        world = World()
        lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=1)
        unit = world.hold_unit(UNIT_TRACKED_PART, lot)

        with pytest.raises(UnitNotRetiredError):
            await world.delete_unit(BENCH, unit.id)

        assert await world.inventory.units.get(unit.id) is not None
        assert world.inventory.commits == 0

    async def test_a_missing_unit_is_a_404(self) -> None:
        world = World()

        with pytest.raises(UnitNotFoundError):
            await world.delete_unit(BENCH, UnitId(uuid7()))

        assert world.inventory.commits == 0


class TestListUnitsOfPart:
    async def test_lists_the_parts_units(self) -> None:
        world = World()
        lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=2)
        first = world.hold_unit(UNIT_TRACKED_PART, lot)
        second = world.hold_unit(UNIT_TRACKED_PART, lot)

        units = await world.list_units_of_part(BENCH, UNIT_TRACKED_PART)

        assert {u.id for u in units} == {first.id, second.id}
        assert world.inventory.commits == 0

    async def test_never_another_parts_units(self) -> None:
        world = World()
        other_part = PartId(uuid7())
        lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=1)
        other_lot = world.hold_lot(other_part, world.drawer, on_hand=1)
        mine = world.hold_unit(UNIT_TRACKED_PART, lot)
        world.hold_unit(other_part, other_lot)

        units = await world.list_units_of_part(BENCH, UNIT_TRACKED_PART)

        assert [u.id for u in units] == [mine.id]

    async def test_a_part_with_no_units_lists_nothing(self) -> None:
        world = World()

        assert await world.list_units_of_part(BENCH, UNIT_TRACKED_PART) == []

    async def test_scopes_the_read_to_the_callers_workspace(self) -> None:
        world = World()

        await world.list_units_of_part(BENCH, UNIT_TRACKED_PART)

        assert world.inventory.opened_for == [BENCH]


class TestListUnitsOfLocation:
    async def test_lists_the_units_sitting_in_the_location(self) -> None:
        world = World()
        lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=2)
        first = world.hold_unit(UNIT_TRACKED_PART, lot)
        second = world.hold_unit(UNIT_TRACKED_PART, lot)

        units = await world.list_units_of_location(BENCH, world.drawer.id)

        assert {u.id for u in units} == {first.id, second.id}
        assert world.inventory.commits == 0

    async def test_gathers_units_across_every_lot_at_the_location(self) -> None:
        world = World()
        # Two parts sitting in the same drawer: both lots are "here".
        other_part = PartId(uuid7())
        one_lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=1)
        another_lot = world.hold_lot(other_part, world.drawer, on_hand=1)
        one = world.hold_unit(UNIT_TRACKED_PART, one_lot)
        another = world.hold_unit(other_part, another_lot)

        units = await world.list_units_of_location(BENCH, world.drawer.id)

        assert {u.id for u in units} == {one.id, another.id}

    async def test_never_another_locations_units(self) -> None:
        world = World()
        box = world.add_location("Parts box", world.lab)
        here_lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=1)
        there_lot = world.hold_lot(UNIT_TRACKED_PART, box, on_hand=1)
        here = world.hold_unit(UNIT_TRACKED_PART, here_lot)
        world.hold_unit(UNIT_TRACKED_PART, there_lot)

        units = await world.list_units_of_location(BENCH, world.drawer.id)

        assert [u.id for u in units] == [here.id]

    async def test_a_location_with_no_units_lists_nothing(self) -> None:
        world = World()

        assert await world.list_units_of_location(BENCH, world.drawer.id) == []


class TestSearchUnits:
    async def test_matches_a_units_code_case_insensitively(self) -> None:
        world = World()
        lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=1)
        unit = world.hold_unit(UNIT_TRACKED_PART, lot)  # WX-U-0001

        found = await world.search_units(BENCH, "wx-u-0001")

        assert [u.id for u in found] == [unit.id]
        assert world.inventory.commits == 0

    async def test_matches_a_serial_as_a_substring(self) -> None:
        world = World()
        lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=1)
        unit = world.hold_unit(UNIT_TRACKED_PART, lot, serial=Serial("SN-ABC-42"))

        found = await world.search_units(BENCH, "abc")

        assert [u.id for u in found] == [unit.id]

    async def test_matches_a_mac_as_a_substring(self) -> None:
        world = World()
        lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=1)
        unit = world.hold_unit(UNIT_TRACKED_PART, lot, mac=Mac("AA-BB-CC-DD-EE-FF"))

        # The stored MAC is canonical, so a colon-and-lower fragment finds it.
        found = await world.search_units(BENCH, "cc:dd")

        assert [u.id for u in found] == [unit.id]

    async def test_a_term_matching_nothing_returns_nothing(self) -> None:
        world = World()
        lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=1)
        world.hold_unit(UNIT_TRACKED_PART, lot)

        assert await world.search_units(BENCH, "no-such-board") == []

    async def test_an_empty_or_blank_term_matches_nothing(self) -> None:
        world = World()
        lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=1)
        world.hold_unit(UNIT_TRACKED_PART, lot)

        # A blank term must not fall through to matching the whole workspace.
        assert await world.search_units(BENCH, "   ") == []
        assert await world.search_units(BENCH, "") == []

    async def test_scopes_the_search_to_the_callers_workspace(self) -> None:
        world = World()

        await world.search_units(BENCH, "wx-u")

        assert world.inventory.opened_for == [BENCH]
