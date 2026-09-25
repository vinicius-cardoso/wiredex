class CatalogError(ValueError):
    """A value or change that breaks a catalog rule. The message is safe to show to users."""


class CategoryNotFoundError(CatalogError):
    pass


class AttributeNotFoundError(CatalogError):
    pass


class PartNotFoundError(CatalogError):
    pass


class DuplicateCategoryNameError(CatalogError):
    pass


class DuplicateAttributeKeyError(CatalogError):
    pass


class DuplicateMpnError(CatalogError):
    pass


class CategoryInUseError(CatalogError):
    """A category with children or parts can't be deleted: nothing is deleted in cascade."""


class CircularCategoryError(CatalogError):
    """A category can't move under itself or one of its descendants."""


class InvalidNumberError(CatalogError):
    """Text that can't be read as a number, including a unit that isn't the attribute's."""


class InvalidUnitError(CatalogError):
    pass
