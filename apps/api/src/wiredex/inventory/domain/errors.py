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
