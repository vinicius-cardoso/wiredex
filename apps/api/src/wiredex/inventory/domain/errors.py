from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # sheet.py and intake.py raise errors from here, so importing them back only for the
    # annotations is what keeps the files from forming a runtime import cycle, as lot.py does.
    from wiredex.inventory.domain.intake import CellProblem, KnownPart
    from wiredex.inventory.domain.sheet import SheetRefusal


class InventoryError(ValueError):
    """A value or change that breaks an inventory rule. The message is safe to show to users."""


class LocationNotFoundError(InventoryError):
    pass


class AmbiguousLocationError(InventoryError):
    """A location path that more than one location's path ends with. The message names each
    one's full path, so the owner can type more of it, or the short code instead."""


class PartNotFoundError(InventoryError):
    """A part the Parts port doesn't know: it doesn't exist in the catalog."""


class LotNotFoundError(InventoryError):
    pass


class DuplicateLocationNameError(InventoryError):
    """Two siblings can't share a name, and two roots count as siblings."""


class LocationInUseError(InventoryError):
    """A location with children or lots can't be deleted: nothing is deleted in cascade."""


class CircularLocationError(InventoryError):
    """A location can't move under itself or one of its descendants."""


class InsufficientStockError(InventoryError):
    """A move or consume asks for more than the source lot holds."""


class ConcurrentStockError(InventoryError):
    """A balance lost the optimistic-lock race too many times: the caller should retry."""


class ReceiveAsUnitsError(InventoryError):
    """A lot receive into a part its category tracks as individual units, which needs units."""


class NotStockedError(InventoryError):
    """New stock for a part its category marks not stocked: a consumable, never counted.

    Stock held before the flag was set keeps working; only what would create stock from
    nothing is refused (09's decision 4).
    """


class SameLocationError(InventoryError):
    """A move's source and destination are the same location, so it would move nothing."""


class NegativeStockError(InventoryError):
    """A movement would drop a lot's on_hand below zero, which the floor forbids."""


class ReservationError(InventoryError):
    """A change would break reserved <= on_hand. Unreachable in v0.4.0, guarded for v0.5.0."""


class InvalidLocationNameError(InventoryError):
    """A location name that is empty or longer than its cap."""


class InvalidShortCodeError(InventoryError):
    """Text that isn't a short code like WX-L-0007."""


class InvalidQuantityError(InventoryError):
    """A quantity that isn't a whole number, or that is negative."""


class InvalidNoteError(InventoryError):
    """A note that is empty or longer than its cap."""


class InvalidSerialError(InventoryError):
    """A serial that is empty or longer than its cap."""


class DuplicateSerialError(InventoryError):
    """Two units of the same part in a workspace can't share a serial, ignoring case."""


class DuplicateMacError(InventoryError):
    """Two units in a workspace can't share a MAC: a MAC is globally unique in reality."""


class UnitNotFoundError(InventoryError):
    """A unit the repository doesn't know in this workspace."""


class UnitNotRetiredError(InventoryError):
    """An in_stock unit asked to be deleted: a unit must be retired before it can be removed."""


class ReceiveAsLotError(InventoryError):
    """A lot-counted part received as units, which needs the loose lot receive instead."""


class SheetUnreadableError(InventoryError):
    """A sheet that can't be read at all (requirements 4.4-4.6): not UTF-8, no header, a
    header that is neither a column nor an attribute key, a column given twice, or a cap
    passed.

    A row's problems are a preview's answer, a 200; this is the one refusal a preview answers
    as a 422. It carries its code, which the web translates, and the column it is about,
    because a sentence alone can't mark a header.
    """

    def __init__(self, code: SheetRefusal, message: str, column: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        # A fixed column's value or an attribute key; the header as typed when it is neither.
        self.column = column


class IntakeRefusedError(InventoryError):
    """A quick-add, or an import whose plan has problems, refused with every problem at once
    (requirements 1.5, 8.2), so the owner fixes them in one pass rather than one per try.

    Each problem names its row and column, which the web marks, and carries a code it
    translates; the message says what was refused as a whole.
    """

    def __init__(self, problems: Iterable[CellProblem], message: str) -> None:
        super().__init__(message)
        self.problems = tuple(problems)


class PartAlreadyDefinedError(InventoryError):
    """A quick-add whose manufacturer and part number a stored part already holds (1.6).

    It carries that part, so the answer can name it and the owner can open it instead.
    """

    def __init__(self, part: KnownPart, message: str) -> None:
        super().__init__(message)
        self.part = part


class ImportChangedError(InventoryError):
    """An import whose sheet no longer plans what its preview showed: the digest it sent
    isn't the plan's now (requirement 8.3). Previewing again shows what it would do."""
