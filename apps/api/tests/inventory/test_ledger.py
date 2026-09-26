"""The ledger: a movement row, a move's two-row group, `Balances.rebuilt_from` folding a
ledger, and property 4 — a move conserves a part's total on_hand across a workspace.

`Balances.rebuilt_from` is the proof `wiredex stock rebuild` rests on: fold the ledger, get
the projection. A `MovementGroup` holds the conservation law of a move so property 4 can
lean on it.
"""

from datetime import UTC, datetime
from uuid import uuid7

import pytest
from hypothesis import given
from hypothesis import strategies as st

from wiredex.inventory.domain.errors import InventoryError
from wiredex.inventory.domain.ledger import Balances, MovementGroup, StockMovement
from wiredex.inventory.domain.lot import StockBalance
from wiredex.inventory.domain.values import (
    MoveGroupId,
    MovementKind,
    MovementReason,
    Note,
    Quantity,
    StockLotId,
    StockMovementId,
    WorkspaceId,
)

NOW = datetime(2026, 9, 25, 10, 0, tzinfo=UTC)
BENCH = WorkspaceId(uuid7())
LOT_A = StockLotId(uuid7())
LOT_B = StockLotId(uuid7())


def movement(
    *,
    lot_id: StockLotId,
    kind: MovementKind,
    change: int,
    move_group: MoveGroupId | None = None,
) -> StockMovement:
    return StockMovement(
        id=StockMovementId(uuid7()),
        workspace_id=BENCH,
        lot_id=lot_id,
        kind=kind,
        change=change,
        reason=None,
        note=None,
        move_group=move_group,
        revision_id=None,
        created_at=NOW,
    )


class TestStockMovement:
    def test_carries_a_signed_change_a_reason_and_a_note(self) -> None:
        adjust = StockMovement(
            id=StockMovementId(uuid7()),
            workspace_id=BENCH,
            lot_id=LOT_A,
            kind=MovementKind.ADJUST,
            change=-3,
            reason=MovementReason.DAMAGED,
            note=Note("dropped two, one cracked"),
            move_group=None,
            revision_id=None,
            created_at=NOW,
        )

        assert adjust.change == -3
        assert adjust.reason is MovementReason.DAMAGED
        assert str(adjust.note) == "dropped two, one cracked"

    def test_a_receive_carries_no_reason_and_no_group(self) -> None:
        received = movement(lot_id=LOT_A, kind=MovementKind.RECEIVE, change=100)

        assert received.reason is None
        assert received.move_group is None

    def test_revision_id_is_none_until_v0_5_0(self) -> None:
        # ADR 0002's "caused by" seam: no use case sets it in v0.4.0.
        assert movement(lot_id=LOT_A, kind=MovementKind.RECEIVE, change=1).revision_id is None


class TestMovementGroup:
    def test_pairs_the_two_rows_of_a_move(self) -> None:
        group_id = MoveGroupId(uuid7())
        out_of = movement(lot_id=LOT_A, kind=MovementKind.MOVE, change=-40, move_group=group_id)
        into = movement(lot_id=LOT_B, kind=MovementKind.MOVE, change=+40, move_group=group_id)

        group = MovementGroup(group_id, out_of, into)

        assert group.rows == (out_of, into)

    def test_refuses_rows_that_do_not_carry_its_id(self) -> None:
        group_id = MoveGroupId(uuid7())
        stray = movement(lot_id=LOT_A, kind=MovementKind.MOVE, change=-40, move_group=None)
        into = movement(lot_id=LOT_B, kind=MovementKind.MOVE, change=+40, move_group=group_id)

        with pytest.raises(InventoryError, match="carry the move group's id"):
            MovementGroup(group_id, stray, into)

    def test_refuses_rows_that_do_not_sum_to_zero(self) -> None:
        group_id = MoveGroupId(uuid7())
        out_of = movement(lot_id=LOT_A, kind=MovementKind.MOVE, change=-40, move_group=group_id)
        into = movement(lot_id=LOT_B, kind=MovementKind.MOVE, change=+30, move_group=group_id)

        with pytest.raises(InventoryError, match="sum to zero"):
            MovementGroup(group_id, out_of, into)


class TestRebuiltFrom:
    def test_folds_one_lots_movements_into_its_balance(self) -> None:
        ledger = [
            movement(lot_id=LOT_A, kind=MovementKind.RECEIVE, change=100),
            movement(lot_id=LOT_A, kind=MovementKind.ADJUST, change=-10),
        ]

        balances = Balances.rebuilt_from(ledger)

        assert int(balances.of(LOT_A).on_hand) == 90

    def test_keeps_lots_apart(self) -> None:
        ledger = [
            movement(lot_id=LOT_A, kind=MovementKind.RECEIVE, change=100),
            movement(lot_id=LOT_B, kind=MovementKind.RECEIVE, change=25),
        ]

        balances = Balances.rebuilt_from(ledger)

        assert int(balances.of(LOT_A).on_hand) == 100
        assert int(balances.of(LOT_B).on_hand) == 25

    def test_an_untouched_lot_reads_as_an_opening_balance(self) -> None:
        balances = Balances.rebuilt_from([])

        opening = balances.of(LOT_A)

        assert int(opening.on_hand) == 0
        assert int(opening.reserved) == 0
        assert opening.version == 0

    def test_reports_only_the_lots_the_ledger_touched(self) -> None:
        ledger = [movement(lot_id=LOT_A, kind=MovementKind.RECEIVE, change=5)]

        balances = Balances.rebuilt_from(ledger)

        assert balances.lots() == frozenset({LOT_A})
        assert [int(b.on_hand) for b in balances.all()] == [5]

    def test_matches_the_incremental_projection(self) -> None:
        # The same numbers apply-at-a-time would reach: rebuild is the ledger's proof (5.3).
        ledger = [
            movement(lot_id=LOT_A, kind=MovementKind.RECEIVE, change=100),
            movement(lot_id=LOT_A, kind=MovementKind.MOVE, change=-40),
            movement(lot_id=LOT_A, kind=MovementKind.ADJUST, change=+5),
        ]
        incremental = StockBalance.opening(LOT_A)
        for m in ledger:
            incremental = incremental.apply(m)

        rebuilt = Balances.rebuilt_from(ledger).of(LOT_A)

        assert int(rebuilt.on_hand) == int(incremental.on_hand) == 65


class TestProperties:
    @given(quantity=st.integers(min_value=1, max_value=10_000))
    def test_property_4_a_move_conserves_total_on_hand(self, quantity: int) -> None:
        """For any move of a valid quantity, the two grouped rows sum to zero, so the
        workspace's total on_hand for that part is unchanged; only its distribution across
        locations changes.

        **Validates: Requirements 4.5, 4.6**
        """
        group_id = MoveGroupId(uuid7())
        out_of = movement(
            lot_id=LOT_A, kind=MovementKind.MOVE, change=-quantity, move_group=group_id
        )
        into = movement(lot_id=LOT_B, kind=MovementKind.MOVE, change=+quantity, move_group=group_id)
        group = MovementGroup(group_id, out_of, into)

        # The pair sums to zero, and folding both rows leaves the two lots' total unchanged
        # from a source that started with exactly enough.
        assert group.out_of.change + group.into.change == 0

        source_start = StockBalance(LOT_A, Quantity(quantity), Quantity(0), version=0)
        dest_start = StockBalance.opening(LOT_B)
        total_before = int(source_start.on_hand) + int(dest_start.on_hand)

        source_after = source_start.apply(out_of)
        dest_after = dest_start.apply(into)
        total_after = int(source_after.on_hand) + int(dest_after.on_hand)

        assert total_after == total_before == quantity
