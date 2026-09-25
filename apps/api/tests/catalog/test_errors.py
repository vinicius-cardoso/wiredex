import pytest

from wiredex.catalog.domain import errors
from wiredex.catalog.domain.errors import CatalogError


@pytest.mark.parametrize(
    "error",
    [
        errors.CategoryNotFoundError,
        errors.AttributeNotFoundError,
        errors.PartNotFoundError,
        errors.DuplicateCategoryNameError,
        errors.DuplicateAttributeKeyError,
        errors.DuplicateMpnError,
        errors.CategoryInUseError,
        errors.CircularCategoryError,
        errors.InvalidNameError,
        errors.InvalidLabelError,
        errors.InvalidAttributeKeyError,
        errors.InvalidPartDetailError,
        errors.InvalidNumberError,
        errors.InvalidUnitError,
        errors.InvalidAttributeOptionsError,
        errors.CategoryTooDeepError,
    ],
)
def test_every_catalog_error_is_a_catalog_error(error: type[Exception]) -> None:
    # The API maps CatalogError to 422 unless a leaf has its own status.
    assert issubclass(error, CatalogError)
    assert issubclass(error, ValueError)
