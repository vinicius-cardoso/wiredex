"""A tracked unit — one physical item with a short code, an optional serial and MAC, and a
status — sitting in a lot.

A unit is *additional identity* over stock that is already counted through the ledger
(design's decision 1), not a second counting system. Its location is its lot's location, so
``lot_id`` is the single pointer and a unit can never disagree with its stock about where it
is. The mutators return whether anything changed, so a no-op skips the ``commit()``; the
compensating movement a retire or un-retire needs is the use case's job, because the entity
can't touch the ledger.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from wiredex.inventory.domain.errors import UnitHeldError
from wiredex.inventory.domain.values import (
    Mac,
    PartId,
    RevisionId,
    Serial,
    ShortCode,
    StockLotId,
    UnitId,
    WorkspaceId,
)


class UnitStatus(StrEnum):
    """A unit's four statuses, from v0.5.0's build lifecycle (design's decision 5).

    Only ``in_stock`` counts toward its lot's ``on_hand`` on its own; ``reserved`` counts too,
    since a reservation holds a piece on hand while setting it aside (requirement 3.9).
    ``in_use`` is a unit built into a revision, sitting on a board rather than in the drawer,
    and ``retired`` is out of stock for good. A held unit — ``reserved`` or ``in_use`` — points
    at the revision that holds it through ``Unit.revision_id``.
    """

    IN_STOCK = "in_stock"
    RESERVED = "reserved"
    IN_USE = "in_use"
    RETIRED = "retired"


@dataclass(eq=False)
class Unit:
    """One individually tracked item of a unit-tracked part.

    Created by receiving units into a location, pointing at that (part, location) lot. The
    code is minted once and never changes or is reused (requirement 2.4). Serial and MAC are
    optional identity; ``status`` is the stock-neutral switch. ``(workspace_id, code)`` is
    unique.

    ``revision_id`` is set exactly while the unit is ``reserved`` or ``in_use``, and cleared
    otherwise, which 0018's CHECK holds (design's decision 5): it is the revision the build
    holds the unit for, the link 15-flash-log will read.
    """

    id: UnitId
    workspace_id: WorkspaceId
    part_id: PartId
    lot_id: StockLotId
    code: ShortCode
    serial: Serial | None
    mac: Mac | None
    status: UnitStatus
    created_at: datetime
    revision_id: RevisionId | None = None
    # When it moved to the trash, None while it is live (16-soft-delete-and-trash, decision 1).
    trashed_at: datetime | None = None

    def relabel(self, serial: Serial | None, mac: Mac | None) -> bool:
        """Sets the serial and MAC, returning whether either changed so an unchanged relabel
        commits nothing (requirement 5.6). Uniqueness is the use case's check, before this.
        """
        if self.serial == serial and self.mac == mac:
            return False
        self.serial = serial
        self.mac = mac
        return True

    def retire(self) -> bool:
        """``in_stock`` → ``retired``, returning whether the status changed.

        A held unit — ``reserved`` or ``in_use`` — can't be retired: a build is holding it, so
        this raises ``UnitHeldError`` saying what frees it (requirement 3.8). A unit already
        retired is a no-op (requirement 3.6): returns False so the use case skips both the
        status write and the compensating ``ADJUST -1``.
        """
        self.ensure_movable()
        if self.status is UnitStatus.RETIRED:
            return False
        self.status = UnitStatus.RETIRED
        return True

    def unretire(self) -> bool:
        """``retired`` → ``in_stock``, returning whether the status changed.

        Un-retiring acts only on a retired unit, so a reserved or in-use one is left where it
        is: this raises ``UnitHeldError`` for a held unit (which a build owns) and returns
        False for one already ``in_stock`` (requirement 3.6), the no-op the use case skips a
        commit on. That fixes the old behaviour of putting any unit that isn't in stock back
        in stock (design's decision 5).
        """
        if self.status is UnitStatus.IN_STOCK:
            return False
        self.ensure_movable()
        self.status = UnitStatus.IN_STOCK
        return True

    def move_to(self, lot_id: StockLotId) -> None:
        """Repoints the unit at the destination lot. The stock effect (the two-row MOVE) is
        the use case's job; here the unit just follows its lot to the new location.
        """
        self.lot_id = lot_id

    def reserve_for(self, revision_id: RevisionId) -> None:
        """``in_stock`` → ``reserved``, linked to the revision (requirement 3.1).

        ``RevisionStock`` reaches this only with a unit it locked in stock, so any other status
        is a bug, not a refusal: it raises ``ValueError``.
        """
        if self.status is not UnitStatus.IN_STOCK:
            raise ValueError("only an in-stock unit can be reserved")
        self.status = UnitStatus.RESERVED
        self.revision_id = revision_id

    def release(self) -> None:
        """``reserved`` → ``in_stock``, the revision link cleared (requirement 3.7).

        A cancelled reservation frees its units. Only a reserved unit is released; any other
        status is a bug (``ValueError``).
        """
        if self.status is not UnitStatus.RESERVED:
            raise ValueError("only a reserved unit can be released")
        self.status = UnitStatus.IN_STOCK
        self.revision_id = None

    def build(self) -> None:
        """``reserved`` → ``in_use``, the revision link kept (requirement 3.6).

        The unit goes onto the board; its ``lot_id`` stays, but it answers no location while in
        use. Only a reserved unit is built; any other status is a bug (``ValueError``).
        """
        if self.status is not UnitStatus.RESERVED:
            raise ValueError("only a reserved unit can be built")
        self.status = UnitStatus.IN_USE

    def return_to(self, lot_id: StockLotId) -> None:
        """``in_use`` → ``in_stock`` in the return lot, the revision link cleared (3.7).

        A dismantled build's units land in the location chosen for the return. Only an in-use
        unit is returned; any other status is a bug (``ValueError``).
        """
        if self.status is not UnitStatus.IN_USE:
            raise ValueError("only an in-use unit can be returned")
        self.status = UnitStatus.IN_STOCK
        self.revision_id = None
        self.lot_id = lot_id

    def ensure_movable(self) -> None:
        """Refuse a reserved or in-use unit with ``UnitHeldError`` (requirement 3.8).

        A move or a retire needs the unit free; a build holds a reserved or in-use one. The
        message names the unit and what frees it, so the owner knows to cancel or dismantle.
        """
        if self.status is UnitStatus.RESERVED:
            raise UnitHeldError(
                f"{self.code} is reserved for a build; cancel the reservation to free it"
            )
        if self.status is UnitStatus.IN_USE:
            raise UnitHeldError(
                f"{self.code} is built into a revision; dismantle the build to free it"
            )

    def ensure_deletable(self) -> None:
        """Refuse a reserved or in-use unit with ``UnitHeldError`` before a delete (3.8).

        The same hold as ``ensure_movable``: 06's delete then refuses an in-stock unit as not
        retired, but a held one hears what frees it first.
        """
        self.ensure_movable()

    def move_to_trash(self, now: datetime) -> None:
        """Out of every list and lookup until it is restored (16-soft-delete-and-trash,
        decision 1). Only a retired unit gets there, as only a retired unit could be
        deleted.

        Nothing else changes, its last update included, so a restored unit comes back as it
        was, where its list had it.
        """
        self.trashed_at = now

    def restore_from_trash(self) -> None:
        """Back in every list and lookup it was in, as it was (16's requirement 5.1)."""
        self.trashed_at = None

    @property
    def in_trash(self) -> bool:
        return self.trashed_at is not None
