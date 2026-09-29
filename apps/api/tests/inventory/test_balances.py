"""The balance projection: `available`, `apply` moving on_hand, the floor and the reserved
guard, and properties 1, 2 and 3 over generated movement sequences.

`apply` is the single place a movement changes a count, so the invariants ADR 0002 names —
on_hand never negative, reserved within on_hand, the ledger summing to the balance — are
pinned here, in the domain, before any adapter can get them wrong.
"""

from datetime import UTC, datetime
from uuid import uuid7

import pytest
from hypothesis import given
from hypothesis import strategies as st

from wiredex.inventory.domain.errors import (
    NegativeStockError,
    ReservationError,
    ReservedStockError,
)
from wiredex.inventory.domain.ledger import StockMovement
from wiredex.inventory.domain.lot import StockBalance, StockLot
from wiredex.inventory.domain.values import (
    LocationId,
    MovementKind,
    PartId,
    Quantity,
    RevisionId,
    StockLotId,
    StockMovementId,
    WorkspaceId,
)

NOW = datetime(2026, 9, 25, 10, 0, tzinfo=UTC)
BENCH = WorkspaceId(uuid7())
LOT = StockLotId(uuid7())
REVISION = RevisionId(uuid7())


def movement(
    change: int, *, kind: MovementKind = MovementKind.ADJUST, lot_id: StockLotId = LOT
) -> StockMovement:
    """A bare movement carrying the kind and its signed change, which is all `apply` reads.

    A kind that must name a revision gets one, so `StockMovement.__post_init__` accepts it."""
    return StockMovement(
        id=StockMovementId(uuid7()),
        workspace_id=BENCH,
        lot_id=lot_id,
        kind=kind,
        change=change,
        reason=None,
        note=None,
        move_group=None,
        revision_id=REVISION if kind.names_a_revision else None,
        created_at=NOW,
    )


class TestStockLot:
    def test_is_the_thin_identity_of_a_part_in_a_location(self) -> None:
        lot = StockLot(LOT, BENCH, PartId(uuid7()), LocationId(uuid7()), NOW)

        assert lot.id == LOT
        assert lot.workspace_id == BENCH


class TestAvailable:
    def test_is_on_hand_minus_reserved(self) -> None:
        balance = StockBalance(LOT, Quantity(40), Quantity(15), version=3)

        assert int(balance.available) == 25

    def test_equals_on_hand_when_nothing_is_reserved(self) -> None:
        # v0.4.0: reserved is always zero, so available == on_hand (requirement 3.5).
        balance = StockBalance(LOT, Quantity(42), Quantity(0), version=0)

        assert int(balance.available) == int(balance.on_hand) == 42


class TestApply:
    def test_moves_on_hand_by_the_signed_change(self) -> None:
        opening = StockBalance.opening(LOT)

        received = opening.apply(movement(+100))

        assert int(received.on_hand) == 100

    def test_a_negative_change_lowers_on_hand(self) -> None:
        balance = StockBalance(LOT, Quantity(100), Quantity(0), version=1)

        after = balance.apply(movement(-40))

        assert int(after.on_hand) == 60

    def test_returns_a_new_balance_and_leaves_the_old_one_untouched(self) -> None:
        opening = StockBalance.opening(LOT)

        received = opening.apply(movement(+5))

        assert received is not opening
        assert int(opening.on_hand) == 0
        assert int(received.on_hand) == 5

    def test_bumps_the_version_for_optimistic_locking(self) -> None:
        balance = StockBalance(LOT, Quantity(1), Quantity(0), version=7)

        assert balance.apply(movement(+1)).version == 8

    def test_a_change_below_zero_is_refused_by_the_floor(self) -> None:
        balance = StockBalance(LOT, Quantity(10), Quantity(0), version=0)

        with pytest.raises(NegativeStockError, match="below zero"):
            balance.apply(movement(-11))

    def test_the_floor_holds_at_exactly_zero(self) -> None:
        balance = StockBalance(LOT, Quantity(10), Quantity(0), version=0)

        assert int(balance.apply(movement(-10)).on_hand) == 0

    def test_an_on_hand_change_that_would_fall_below_reserved_is_refused(self) -> None:
        # An ADJUST dropping on_hand under the reservation is the hard hold (requirement 7.1).
        held = StockBalance(LOT, Quantity(10), Quantity(8), version=0)

        with pytest.raises(ReservedStockError, match="below the 8 reserved"):
            held.apply(movement(-5))  # on_hand would fall to 5, below reserved 8

    def test_reserved_may_equal_on_hand(self) -> None:
        held = StockBalance(LOT, Quantity(10), Quantity(8), version=0)

        after = held.apply(movement(-2))  # on_hand to 8, exactly reserved

        assert int(after.on_hand) == int(after.reserved) == 8


class TestApplyByKind:
    """`apply` moves on_hand by RECEIVE, ADJUST, MOVE, CONSUME and RETURN, reserved by RESERVE,
    RELEASE and CONSUME, each by the movement's change (requirements 2.6, 7.3, 8.3)."""

    def test_reserve_raises_reserved_and_leaves_on_hand(self) -> None:
        balance = StockBalance(LOT, Quantity(10), Quantity(0), version=0)

        after = balance.apply(movement(+4, kind=MovementKind.RESERVE))

        assert int(after.on_hand) == 10
        assert int(after.reserved) == 4
        assert int(after.available) == 6

    def test_release_lowers_reserved_and_leaves_on_hand(self) -> None:
        balance = StockBalance(LOT, Quantity(10), Quantity(4), version=0)

        after = balance.apply(movement(-3, kind=MovementKind.RELEASE))

        assert int(after.on_hand) == 10
        assert int(after.reserved) == 1

    def test_consume_lowers_on_hand_and_reserved_together(self) -> None:
        balance = StockBalance(LOT, Quantity(10), Quantity(4), version=0)

        after = balance.apply(movement(-4, kind=MovementKind.CONSUME))

        assert int(after.on_hand) == 6
        assert int(after.reserved) == 0

    def test_return_raises_on_hand_and_leaves_reserved(self) -> None:
        balance = StockBalance(LOT, Quantity(6), Quantity(2), version=0)

        after = balance.apply(movement(+4, kind=MovementKind.RETURN))

        assert int(after.on_hand) == 10
        assert int(after.reserved) == 2

    def test_a_recount_below_reserved_raises_reserved_stock(self) -> None:
        # ADJUST moves on_hand only; dropping it under the reservation is the hard hold (7.1).
        held = StockBalance(LOT, Quantity(10), Quantity(6), version=0)

        with pytest.raises(ReservedStockError, match="6 reserved") as raised:
            held.apply(movement(-5, kind=MovementKind.ADJUST))  # on_hand to 5, below reserved 6

        assert raised.value.reserved == 6

    def test_a_move_out_past_available_raises_reserved_stock(self) -> None:
        # A MOVE out is an on-hand movement; it can't eat into the reservation (7.2).
        held = StockBalance(LOT, Quantity(10), Quantity(6), version=0)

        with pytest.raises(ReservedStockError, match="6 reserved"):
            held.apply(movement(-5, kind=MovementKind.MOVE))

    def test_a_reserve_past_on_hand_is_a_plain_reservation_error(self) -> None:
        balance = StockBalance(LOT, Quantity(10), Quantity(8), version=0)

        with pytest.raises(ReservationError, match="can't exceed on_hand") as raised:
            balance.apply(movement(+3, kind=MovementKind.RESERVE))  # reserved to 11, above 10

        assert not isinstance(raised.value, ReservedStockError)

    def test_a_release_below_zero_is_refused(self) -> None:
        balance = StockBalance(LOT, Quantity(10), Quantity(2), version=0)

        with pytest.raises(ReservationError, match="below zero"):
            balance.apply(movement(-3, kind=MovementKind.RELEASE))  # reserved to -1


# A movement of any kind whose change's sign its kind allows, over an opening balance: the
# shape properties 2 and 3 fold. RECEIVE, ADJUST and MOVE take either sign; RESERVE and RETURN
# are positive, RELEASE and CONSUME negative.
_SIGN_FREE = (MovementKind.RECEIVE, MovementKind.ADJUST, MovementKind.MOVE)
_POSITIVE = (MovementKind.RESERVE, MovementKind.RETURN)
_NEGATIVE = (MovementKind.RELEASE, MovementKind.CONSUME)


@st.composite
def _movements(draw: st.DrawFn) -> StockMovement:
    kind = draw(st.sampled_from(list(MovementKind)))
    if kind in _POSITIVE:
        change = draw(st.integers(min_value=1, max_value=1000))
    elif kind in _NEGATIVE:
        change = draw(st.integers(min_value=-1000, max_value=-1))
    else:
        change = draw(st.integers(min_value=-1000, max_value=1000))
    return movement(change, kind=kind)


sequences = st.lists(_movements(), max_size=40)


class TestProperties:
    @given(sequence=sequences)
    def test_property_2_each_movement_moves_the_balance_by_its_kind(
        self, sequence: list[StockMovement]
    ) -> None:
        """For any balance with 0 <= reserved <= on_hand and any movement of any of the seven
        kinds, `apply` either answers on_hand moved by the change when the kind moves on_hand,
        reserved moved by it when the kind moves reserved, each otherwise as it was, and the
        version one on — or raises; it raises exactly when the result would break
        0 <= reserved <= on_hand, so every balance it answers keeps it, with available equal
        to on_hand less reserved.

        **Validates: Requirements 2.6, 7.3, 7.4, 8.3**
        """
        balance = StockBalance.opening(LOT)
        for m in sequence:
            before = balance
            expected_on_hand = int(before.on_hand) + (m.change if m.kind.moves_on_hand else 0)
            expected_reserved = int(before.reserved) + (m.change if m.kind.moves_reserved else 0)
            keeps_bounds = 0 <= expected_reserved <= expected_on_hand
            try:
                balance = before.apply(m)
            except NegativeStockError, ReservationError:
                # A refused step changes nothing, and it is refused exactly when the result
                # would break the bounds.
                assert not keeps_bounds
                assert balance is before
                continue
            assert keeps_bounds
            assert int(balance.on_hand) == expected_on_hand
            assert int(balance.reserved) == expected_reserved
            assert balance.version == before.version + 1
            assert 0 <= int(balance.reserved) <= int(balance.on_hand)
            assert int(balance.available) == int(balance.on_hand) - int(balance.reserved)

    @given(sequence=sequences)
    def test_the_ledger_sums_to_the_balance_per_count(self, sequence: list[StockMovement]) -> None:
        """05's ledger-sums-to-the-balance restated per count: for any sequence of movements
        of any kinds on one lot, on_hand is the sum of the changes of the kinds that move it,
        and reserved the sum of the changes of the kinds that move reserved (design's Inventory:
        movements and balances).

        **Validates: Requirements 8.3, 8.4**
        """
        balance = StockBalance.opening(LOT)
        on_hand = 0
        reserved = 0
        for m in sequence:
            try:
                balance = balance.apply(m)
            except NegativeStockError, ReservationError:
                continue
            if m.kind.moves_on_hand:
                on_hand += m.change
            if m.kind.moves_reserved:
                reserved += m.change
            assert int(balance.on_hand) == on_hand
            assert int(balance.reserved) == reserved
