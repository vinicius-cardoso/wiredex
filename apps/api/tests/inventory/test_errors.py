import pytest

from wiredex.inventory.domain import errors
from wiredex.inventory.domain.errors import InventoryError


@pytest.mark.parametrize(
    "error",
    [
        errors.LocationNotFoundError,
        errors.PartNotFoundError,
        errors.LotNotFoundError,
        errors.DuplicateLocationNameError,
        errors.LocationInUseError,
        errors.CircularLocationError,
        errors.InsufficientStockError,
        errors.ConcurrentStockError,
        errors.ReceiveAsUnitsError,
        errors.SameLocationError,
        errors.NegativeStockError,
        errors.ReservationError,
        errors.DuplicateSerialError,
        errors.DuplicateMacError,
        errors.UnitNotFoundError,
        errors.UnitNotRetiredError,
        errors.ReceiveAsLotError,
        errors.InvalidSerialError,
    ],
)
def test_every_inventory_error_is_an_inventory_error(error: type[Exception]) -> None:
    # The API maps InventoryError to 422 unless a leaf has its own status.
    assert issubclass(error, InventoryError)
    assert issubclass(error, ValueError)
