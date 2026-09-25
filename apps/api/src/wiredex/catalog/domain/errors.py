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


class InvalidNameError(CatalogError):
    """A category or part name that is empty or longer than its cap."""


class InvalidLabelError(CatalogError):
    """An attribute label that is empty or longer than its cap."""


class InvalidAttributeKeyError(CatalogError):
    """A key that isn't a lower-case slug, which it has to be: it names a JSONB field."""


class InvalidPartDetailError(CatalogError):
    """A manufacturer, MPN or package that is empty or longer than its cap."""


class InvalidNumberError(CatalogError):
    """Text that can't be read as a number, including a unit that isn't the attribute's."""


class InvalidUnitError(CatalogError):
    pass


class InvalidAttributeOptionsError(CatalogError):
    """A choice attribute with nothing to choose from, or options on a kind that has none."""


class CategoryTooDeepError(CatalogError):
    """A category, or a subtree moving with it, would sit deeper than the tree cap allows."""
