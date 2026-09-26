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

from wiredex.inventory.domain.errors import NegativeStockError, ReservationError
from wiredex.inventory.domain.ledger import StockMovement
from wiredex.inventory.domain.lot import StockBalance, StockLot
from wiredex.inventory.domain.values import (
    LocationId,
    MovementKind,
    PartId,
    Quantity,
    StockLotId,
    StockMovementId,
    WorkspaceId,
)

NOW = datetime(2026, 9, 25, 10, 0, tzinfo=UTC)
BENCH = WorkspaceId(uuid7())
LOT = StockLotId(uuid7())


def movement(change: int, *, lot_id: StockLotId = LOT) -> StockMovement:
    """A bare movement carrying just the signed change, which is all `apply` reads of it."""
    return StockMovement(
        id=StockMovementId(uuid7()),
        workspace_id=BENCH,
        lot_id=lot_id,
        kind=MovementKind.ADJUST,
        change=change,
        reason=None,
        note=None,
        move_group=None,
        revision_id=None,
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

    def test_a_change_that_would_leave_reserved_above_on_hand_is_refused(self) -> None:
        # Unreachable in v0.4.0 (no movement reserves), but guarded so v0.5.0 inherits it.
        held = StockBalance(LOT, Quantity(10), Quantity(8), version=0)

        with pytest.raises(ReservationError, match="can't exceed on_hand"):
            held.apply(movement(-5))  # on_hand would fall to 5, below reserved 8

    def test_reserved_may_equal_on_hand(self) -> None:
        held = StockBalance(LOT, Quantity(10), Quantity(8), version=0)

        after = held.apply(movement(-2))  # on_hand to 8, exactly reserved

        assert int(after.on_hand) == int(after.reserved) == 8


# A sequence of signed changes applied from an opening balance, the shape properties 1-3 fold.
changes = st.lists(st.integers(min_value=-1000, max_value=1000), max_size=40)


class TestProperties:
    @given(changes=changes)
    def test_property_1_on_hand_never_goes_negative(self, changes: list[int]) -> None:
        """For any sequence of movements, on_hand is >= 0 at every step, and a movement that
        would take it below zero raises rather than storing a bad balance.

        **Validates: Requirements 3.6, 5.4**
        """
        balance = StockBalance.opening(LOT)
        for change in changes:
            try:
                balance = balance.apply(movement(change))
            except NegativeStockError, ReservationError:
                # A refused step changes nothing; the last good balance still holds.
                assert int(balance.on_hand) >= 0
                continue
            assert int(balance.on_hand) >= 0

    @given(changes=changes)
    def test_property_2_reserved_stays_within_on_hand(self, changes: list[int]) -> None:
        """For any sequence, 0 <= reserved <= on_hand and available == on_hand - reserved hold
        at every step. In v0.4.0 no movement reserves, so this reduces to available == on_hand;
        the property is written over the general `apply`, so v0.5.0 inherits it proven.

        **Validates: Requirements 3.4, 3.5, 3.7**
        """
        balance = StockBalance.opening(LOT)
        for change in changes:
            try:
                balance = balance.apply(movement(change))
            except NegativeStockError, ReservationError:
                continue
            assert 0 <= int(balance.reserved) <= int(balance.on_hand)
            assert int(balance.available) == int(balance.on_hand) - int(balance.reserved)

    @given(changes=changes)
    def test_property_3_the_ledger_sums_to_the_balance(self, changes: list[int]) -> None:
        """For any sequence of movements on one lot, folding their signed change from zero
        equals the lot's on_hand.

        **Validates: Requirements 5.1, 5.4**
        """
        balance = StockBalance.opening(LOT)
        applied: list[int] = []
        for change in changes:
            try:
                balance = balance.apply(movement(change))
            except NegativeStockError, ReservationError:
                continue
            applied.append(change)
            assert sum(applied) == int(balance.on_hand)
