class InventoryError(ValueError):
    """A value or change that breaks an inventory rule. The message is safe to show to users."""


class LocationNotFoundError(InventoryError):
    pass


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
