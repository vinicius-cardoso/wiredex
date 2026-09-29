"""The append-only movement ledger and the balance projection folded from it.

A `StockMovement` is one immutable row: one lot, one signed change, one kind. A `MOVE` is
two rows sharing one `MoveGroupId`, a `MovementGroup`, so the pair is conserved (their
changes sum to zero). `Balances` folds a whole ledger back into balances, so "the projection
equals the sum of the ledger" is one method — the proof `wiredex stock rebuild` rests on.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from wiredex.inventory.domain.errors import InventoryError
from wiredex.inventory.domain.lot import StockBalance
from wiredex.inventory.domain.values import (
    MoveGroupId,
    MovementKind,
    MovementReason,
    Note,
    RevisionId,
    StockLotId,
    StockMovementId,
    WorkspaceId,
)


@dataclass(eq=False)
class StockMovement:
    """One append-only ledger row. Immutable: nothing updates or deletes it (ADR 0002).

    `change` is signed — positive on a RECEIVE, either sign on an ADJUST delta, and the two
    opposite signs on a MOVE's pair. `reason` is set on an ADJUST and None otherwise;
    `move_group` is set on the two rows of a MOVE and None otherwise; `revision_id` is
    ADR 0002's "caused by": the four v0.5.0 kinds (RESERVE, RELEASE, CONSUME, RETURN) name a
    revision and the other three don't. `__post_init__` refuses what 0018's two CHECKs will —
    a revision on the wrong kind, or a wrong sign — so a bug fails in a unit test, not at the
    commit; only a bug builds such a row, so no route answers it (design decision 15).
    """

    id: StockMovementId
    workspace_id: WorkspaceId
    lot_id: StockLotId
    kind: MovementKind
    change: int
    reason: MovementReason | None
    note: Note | None
    move_group: MoveGroupId | None
    revision_id: RevisionId | None
    created_at: datetime

    def __post_init__(self) -> None:
        if self.kind.names_a_revision != (self.revision_id is not None):
            named = "must name" if self.kind.names_a_revision else "must not name"
            raise ValueError(f"a {self.kind} movement {named} a revision")
        if not self.kind.sign_allows(self.change):
            raise ValueError(f"a change of {self.change} is not allowed for a {self.kind} movement")


@dataclass(frozen=True, slots=True)
class MovementGroup:
    """The two rows of a MOVE, sharing one `MoveGroupId`: a withdrawal and an equal deposit.

    Grouping them makes the conservation law (property 4) a thing you can hold: the pair's
    changes sum to zero, so a move never invents or loses stock, it only relocates it.
    """

    id: MoveGroupId
    out_of: StockMovement
    into: StockMovement

    def __post_init__(self) -> None:
        if self.out_of.move_group != self.id or self.into.move_group != self.id:
            raise InventoryError("both rows of a move must carry the move group's id")
        if self.out_of.change + self.into.change != 0:
            raise InventoryError("a move's two rows must sum to zero, so total stock is kept")

    @property
    def rows(self) -> tuple[StockMovement, StockMovement]:
        """The two rows to append, source first, so the caller writes them in one go."""
        return (self.out_of, self.into)


class Balances:
    """A first-class collection of balances, folded from a ledger.

    `rebuilt_from` streams a ledger — in any order within a lot is fine, since a lot's rows
    are summed — and folds each lot's movements onto its opening balance. `stock rebuild`
    uses it to recompute the whole projection and prove the incremental one (property 6).
    """

    def __init__(self, by_lot: dict[StockLotId, StockBalance]) -> None:
        self._by_lot = by_lot

    @classmethod
    def rebuilt_from(cls, movements: Iterable[StockMovement]) -> Balances:
        """Fold a ledger into balances, grouped by lot, each from its opening balance.

        `apply` is the same step the incremental path takes, so a rebuild reaches the same
        numbers a movement-at-a-time projection did (property 6). It raises the same
        `NegativeStockError` if the ledger itself is impossible, which a real ledger never is.
        """
        by_lot: dict[StockLotId, StockBalance] = {}
        for movement in movements:
            current = by_lot.get(movement.lot_id) or StockBalance.opening(movement.lot_id)
            by_lot[movement.lot_id] = current.apply(movement)
        return cls(by_lot)

    def of(self, lot_id: StockLotId) -> StockBalance:
        """The balance of a lot, or its opening balance when the ledger never touched it."""
        return self._by_lot.get(lot_id) or StockBalance.opening(lot_id)

    def lots(self) -> frozenset[StockLotId]:
        """Every lot the ledger touched, so a caller can replace exactly those balances."""
        return frozenset(self._by_lot)

    def all(self) -> Iterable[StockBalance]:
        """Every folded balance, for `BalanceSheet.replace_all` during a rebuild."""
        return tuple(self._by_lot.values())
