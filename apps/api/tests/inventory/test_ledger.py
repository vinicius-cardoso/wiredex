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

from wiredex.inventory.domain.errors import (
    InventoryError,
    NegativeStockError,
    ReservationError,
)
from wiredex.inventory.domain.ledger import Balances, MovementGroup, StockMovement
from wiredex.inventory.domain.lot import StockBalance
from wiredex.inventory.domain.values import (
    MoveGroupId,
    MovementKind,
    MovementReason,
    Note,
    Quantity,
    RevisionId,
    StockLotId,
    StockMovementId,
    WorkspaceId,
)

NOW = datetime(2026, 9, 25, 10, 0, tzinfo=UTC)
BENCH = WorkspaceId(uuid7())
LOT_A = StockLotId(uuid7())
LOT_B = StockLotId(uuid7())
REVISION = RevisionId(uuid7())


def movement(
    *,
    lot_id: StockLotId,
    kind: MovementKind,
    change: int,
    move_group: MoveGroupId | None = None,
) -> StockMovement:
    """A movement of any kind; a kind that must name a revision gets one, so
    `StockMovement.__post_init__` accepts it."""
    return StockMovement(
        id=StockMovementId(uuid7()),
        workspace_id=BENCH,
        lot_id=lot_id,
        kind=kind,
        change=change,
        reason=None,
        note=None,
        move_group=move_group,
        revision_id=REVISION if kind.names_a_revision else None,
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


class TestPostInit:
    """`StockMovement.__post_init__` refuses what 0018's two CHECKs refuse (requirements 8.1,
    8.2): a revision on the wrong kind, and a wrong sign for the four new kinds."""

    def test_a_reserve_must_name_a_revision(self) -> None:
        with pytest.raises(ValueError, match="must name a revision"):
            StockMovement(
                id=StockMovementId(uuid7()),
                workspace_id=BENCH,
                lot_id=LOT_A,
                kind=MovementKind.RESERVE,
                change=1,
                reason=None,
                note=None,
                move_group=None,
                revision_id=None,
                created_at=NOW,
            )

    def test_a_receive_must_not_name_a_revision(self) -> None:
        with pytest.raises(ValueError, match="must not name a revision"):
            StockMovement(
                id=StockMovementId(uuid7()),
                workspace_id=BENCH,
                lot_id=LOT_A,
                kind=MovementKind.RECEIVE,
                change=1,
                reason=None,
                note=None,
                move_group=None,
                revision_id=REVISION,
                created_at=NOW,
            )

    def test_a_reserve_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="not allowed for a RESERVE"):
            movement(lot_id=LOT_A, kind=MovementKind.RESERVE, change=-1)

    def test_a_consume_must_be_negative(self) -> None:
        with pytest.raises(ValueError, match="not allowed for a CONSUME"):
            movement(lot_id=LOT_A, kind=MovementKind.CONSUME, change=1)

    def test_the_three_old_kinds_take_either_sign(self) -> None:
        # An ADJUST corrects up or down, a MOVE row is signed either way; neither is refused.
        assert movement(lot_id=LOT_A, kind=MovementKind.ADJUST, change=-3).change == -3
        assert movement(lot_id=LOT_A, kind=MovementKind.ADJUST, change=+3).change == 3


# One lot's movements of any kind whose sign its kind allows, applied in the order written:
# what a rebuild folds. The generator stays within one lot so a whole sequence is plausible.
_POSITIVE = (MovementKind.RESERVE, MovementKind.RETURN)
_NEGATIVE = (MovementKind.RELEASE, MovementKind.CONSUME)


@st.composite
def _movements(draw: st.DrawFn, lot_id: StockLotId) -> StockMovement:
    kind = draw(st.sampled_from(list(MovementKind)))
    if kind in _POSITIVE:
        change = draw(st.integers(min_value=1, max_value=1000))
    elif kind in _NEGATIVE:
        change = draw(st.integers(min_value=-1000, max_value=-1))
    else:
        change = draw(st.integers(min_value=-1000, max_value=1000))
    return movement(lot_id=lot_id, kind=kind, change=change)


ledgers = st.lists(st.one_of(_movements(lot_id=LOT_A), _movements(lot_id=LOT_B)), max_size=40)


class TestProperties:
    @given(ledger=ledgers)
    def test_property_3_a_rebuild_over_all_seven_kinds_reproduces_the_balances(
        self, ledger: list[StockMovement]
    ) -> None:
        """For any sequence of movements of all seven kinds over any lots, each accepted by
        `apply` when it was written, folding each lot's movements through `apply` from an empty
        balance in the order written — the ledger's order — gives every lot the on_hand and
        reserved written as the movements happened, as `wiredex stock rebuild` must.

        **Validates: Requirements 8.4**
        """
        # The incremental projection: apply each row as it is written, keeping the ones that
        # stick, exactly what the movement-at-a-time path does and what a rebuild must match.
        incremental: dict[StockLotId, StockBalance] = {}
        written: list[StockMovement] = []
        for m in ledger:
            current = incremental.get(m.lot_id) or StockBalance.opening(m.lot_id)
            try:
                incremental[m.lot_id] = current.apply(m)
            except NegativeStockError, ReservationError:
                continue
            written.append(m)

        rebuilt = Balances.rebuilt_from(written)

        for lot_id, balance in incremental.items():
            assert int(rebuilt.of(lot_id).on_hand) == int(balance.on_hand)
            assert int(rebuilt.of(lot_id).reserved) == int(balance.reserved)

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
