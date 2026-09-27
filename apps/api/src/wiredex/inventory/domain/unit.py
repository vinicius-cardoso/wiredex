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

from wiredex.inventory.domain.values import (
    Mac,
    PartId,
    Serial,
    ShortCode,
    StockLotId,
    UnitId,
    WorkspaceId,
)


class UnitStatus(StrEnum):
    """A unit's two v0.4.0 statuses. Only ``in_stock`` counts toward its lot's ``on_hand``.

    ``in_use``/``reserved`` belong to the v0.5.0 build lifecycle (requirement 3.7), so the
    enum stays at two values and the table's CHECK can't store a stray third.
    """

    IN_STOCK = "in_stock"
    RETIRED = "retired"


@dataclass(eq=False)
class Unit:
    """One individually tracked item of a unit-tracked part.

    Created by receiving units into a location, pointing at that (part, location) lot. The
    code is minted once and never changes or is reused (requirement 2.4). Serial and MAC are
    optional identity; ``status`` is the stock-neutral switch. ``(workspace_id, code)`` is
    unique.
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

        A unit that is already retired is a no-op (requirement 3.6): returns False so the use
        case skips both the status write and the compensating ``ADJUST -1``.
        """
        if self.status is UnitStatus.RETIRED:
            return False
        self.status = UnitStatus.RETIRED
        return True

    def unretire(self) -> bool:
        """``retired`` → ``in_stock``, returning whether the status changed.

        A unit that is already ``in_stock`` is a no-op (requirement 3.6): returns False so the
        use case skips both the status write and the compensating ``ADJUST +1``.
        """
        if self.status is UnitStatus.IN_STOCK:
            return False
        self.status = UnitStatus.IN_STOCK
        return True

    def move_to(self, lot_id: StockLotId) -> None:
        """Repoints the unit at the destination lot. The stock effect (the two-row MOVE) is
        the use case's job; here the unit just follows its lot to the new location.
        """
        self.lot_id = lot_id
