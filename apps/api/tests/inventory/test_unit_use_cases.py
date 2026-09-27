"""The unit use cases over the in-memory fakes. This module covers `ReceiveUnits` (task 4).

Receiving N units of a unit-tracked part writes the ordinary lot + `RECEIVE` + balance and
creates N units with consecutive `WX-U-NNNN` codes, in one transaction — the mirror of the lot
`ReceiveStock`. A lot-counted part is refused (`ReceiveAsLotError`), a part the catalog doesn't
know is a 404, and a duplicate serial (per part) or MAC (per workspace) is refused before a
single row is written. Property 1 pins the invariant (a lot's on_hand equals its in_stock
units) and property 4 the codes (distinct, consecutive within a receipt).
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
    PartNotFoundError,
    ReceiveAsLotError,
)
from wiredex.inventory.domain.unit import UnitStatus
from wiredex.inventory.domain.values import Mac, MovementKind, PartId, Serial

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
