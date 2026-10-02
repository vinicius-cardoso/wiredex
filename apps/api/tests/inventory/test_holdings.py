"""`HeldStock.of` folding a revision's ledger sums into what it holds: nothing while a draft
or dismantled, its reservation per lot while reserved, its consumption per part while built.

The fold is the whole of decision 1 — holdings live in the ledger, with no table — so it is
pinned in the domain, over the four lifecycle states and over any sequence of a revision's
sums.
"""

from uuid import uuid7

from hypothesis import given
from hypothesis import strategies as st

from wiredex.inventory.domain.holdings import HeldStock, LotHolding, MovementSum, PartHeld
from wiredex.inventory.domain.values import (
    LocationId,
    MovementKind,
    PartId,
    StockLotId,
)

PART = PartId(uuid7())
OTHER_PART = PartId(uuid7())
LOC_A = LocationId(uuid7())
LOC_B = LocationId(uuid7())
LOT_A = StockLotId(uuid7())
LOT_B = StockLotId(uuid7())
# Another part's lot, in the second location.
LOT_C = StockLotId(uuid7())

# A lot is one part in one location, so its part and location are fixed once here; a
# MovementSum for the lot carries them, whatever its kind.
_WHERE: dict[StockLotId, tuple[LocationId, str]] = {
    LOT_A: (LOC_A, "WX-L-0001"),
    LOT_B: (LOC_B, "WX-L-0002"),
    LOT_C: (LOC_B, "WX-L-0002"),
}


def summed(
    *, kind: MovementKind, change: int, lot_id: StockLotId = LOT_A, part_id: PartId = PART
) -> MovementSum:
    """One (lot, kind) sum, the shape the database groups a revision's rows into."""
    location_id, location_code = _WHERE[lot_id]
    return MovementSum(
        lot_id=lot_id,
        part_id=part_id,
        location_id=location_id,
        location_code=location_code,
        kind=kind,
        change=change,
    )


class TestDraft:
    def test_a_revision_with_no_movements_holds_nothing(self) -> None:
        # A draft has never touched the ledger.
        held = HeldStock.of([])

        assert held.reserved == ()
        assert held.consumed == {}


class TestReserved:
    def test_a_reserve_is_held_per_lot(self) -> None:
        held = HeldStock.of([summed(kind=MovementKind.RESERVE, change=+3)])

        assert held.reserved == (
            LotHolding(
                lot_id=LOT_A,
                part_id=PART,
                location_id=LOC_A,
                location_code="WX-L-0001",
                quantity=3,
            ),
        )
        assert held.consumed == {}

    def test_reservations_across_lots_are_each_their_own_holding(self) -> None:
        held = HeldStock.of(
            [
                summed(kind=MovementKind.RESERVE, change=+3, lot_id=LOT_A),
                summed(kind=MovementKind.RESERVE, change=+1, lot_id=LOT_B),
            ]
        )

        by_lot = {holding.lot_id: holding.quantity for holding in held.reserved}
        assert by_lot == {LOT_A: 3, LOT_B: 1}


class TestBuilt:
    def test_a_build_consumes_per_part_and_reserves_nothing(self) -> None:
        # A build releases the reservation as it consumes: a positive RESERVE then a negative
        # CONSUME on the lot net to zero reserved, and the CONSUME is what the part holds.
        held = HeldStock.of(
            [
                summed(kind=MovementKind.RESERVE, change=+4),
                summed(kind=MovementKind.CONSUME, change=-4),
            ]
        )

        assert held.reserved == ()
        assert held.consumed == {PART: 4}

    def test_consumption_sums_a_parts_lots(self) -> None:
        held = HeldStock.of(
            [
                summed(kind=MovementKind.RESERVE, change=+3, lot_id=LOT_A),
                summed(kind=MovementKind.CONSUME, change=-3, lot_id=LOT_A),
                summed(kind=MovementKind.RESERVE, change=+1, lot_id=LOT_B),
                summed(kind=MovementKind.CONSUME, change=-1, lot_id=LOT_B),
            ]
        )

        assert held.reserved == ()
        assert held.consumed == {PART: 4}


class TestDismantled:
    def test_a_dismantled_revision_holds_nothing(self) -> None:
        # A positive RESERVE, a negative CONSUME then a positive RETURN: the lot's reserved
        # nets to zero and the part's consumption to zero, so a dismantled revision holds none.
        held = HeldStock.of(
            [
                summed(kind=MovementKind.RESERVE, change=+5),
                summed(kind=MovementKind.CONSUME, change=-5),
                summed(kind=MovementKind.RETURN, change=+5),
            ]
        )

        assert held.reserved == ()
        assert held.consumed == {}


class TestCancelled:
    def test_a_reserve_then_a_release_holds_nothing(self) -> None:
        # A cancel back to draft: a positive RESERVE then a negative RELEASE net to zero.
        held = HeldStock.of(
            [
                summed(kind=MovementKind.RESERVE, change=+2),
                summed(kind=MovementKind.RELEASE, change=-2),
            ]
        )

        assert held.reserved == ()
        assert held.consumed == {}


class TestPerPart:
    """What a revision holds of each part, which the dashboard regroups across revisions
    (18-dashboard, decision 1)."""

    def test_a_reservation_over_two_lots_is_one_part(self) -> None:
        held = HeldStock.of(
            [
                summed(kind=MovementKind.RESERVE, change=+3, lot_id=LOT_A),
                summed(kind=MovementKind.RESERVE, change=+2, lot_id=LOT_B),
                summed(kind=MovementKind.RESERVE, change=+1, lot_id=LOT_C, part_id=OTHER_PART),
            ]
        )

        assert held.per_part() == {PART: PartHeld(5, 0), OTHER_PART: PartHeld(1, 0)}

    def test_a_build_holds_what_it_consumed(self) -> None:
        held = HeldStock.of(
            [
                summed(kind=MovementKind.RESERVE, change=+4),
                summed(kind=MovementKind.CONSUME, change=-4),
            ]
        )

        assert held.per_part() == {PART: PartHeld(0, 4)}

    def test_a_cancelled_or_dismantled_revision_holds_no_part(self) -> None:
        cancelled = HeldStock.of(_rows_for("cancelled", LOT_A, 2))
        dismantled = HeldStock.of(_rows_for("dismantled", LOT_B, 3))

        assert cancelled.per_part() == {}
        assert dismantled.per_part() == {}


# A revision passes through one lifecycle at a time, so its rows on a lot follow one of the
# four shapes below; a draft has none. Building the sums from the state keeps every generated
# sequence one a real ledger could hold.
def _rows_for(state: str, lot_id: StockLotId, qty: int) -> list[MovementSum]:
    reserve = summed(kind=MovementKind.RESERVE, change=+qty, lot_id=lot_id)
    consume = summed(kind=MovementKind.CONSUME, change=-qty, lot_id=lot_id)
    release = summed(kind=MovementKind.RELEASE, change=-qty, lot_id=lot_id)
    ret = summed(kind=MovementKind.RETURN, change=+qty, lot_id=lot_id)
    return {
        "reserved": [reserve],
        "built": [reserve, consume],
        "dismantled": [reserve, consume, ret],
        "cancelled": [reserve, release],
    }[state]


_STATES = ("reserved", "built", "dismantled", "cancelled")


class TestProperties:
    @given(
        state=st.sampled_from(_STATES),
        rows=st.lists(
            st.tuples(st.sampled_from([LOT_A, LOT_B]), st.integers(min_value=1, max_value=1000)),
            max_size=8,
            unique_by=lambda row: row[0],
        ),
    )
    def test_holdings_come_from_the_ledger_over_every_lifecycle_state(
        self, state: str, rows: list[tuple[StockLotId, int]]
    ) -> None:
        """For a revision in any one lifecycle state, over any lots and quantities,
        `HeldStock.of` answers exactly what the ledger says it holds: while reserved the RESERVE
        per lot and no consumption; while built the CONSUME per part and no reservation; and
        nothing while cancelled or dismantled, its rows summing to zero.

        **Validates: Requirements 8.5, 8.6, 14.6**
        """
        sums: list[MovementSum] = []
        for lot_id, qty in rows:
            sums.extend(_rows_for(state, lot_id, qty))

        held = HeldStock.of(sums)

        if state == "reserved":
            assert {h.lot_id: h.quantity for h in held.reserved} == dict(rows)
            assert held.consumed == {}
        elif state == "built":
            assert held.reserved == ()
            assert held.consumed == ({PART: sum(qty for _, qty in rows)} if rows else {})
        else:
            # Cancelled or dismantled: everything nets to zero, so nothing is held.
            assert held.reserved == ()
            assert held.consumed == {}
