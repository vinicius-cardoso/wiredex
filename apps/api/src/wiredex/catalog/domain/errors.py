from enum import StrEnum


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


class InvalidPinNumberError(CatalogError):
    """A pin number that is empty, too long, or spelled outside A-Z 0-9 _ . + -."""


class InvalidPinLabelError(CatalogError):
    """A pin label that is empty or longer than its cap."""


class InvalidPinFunctionError(CatalogError):
    """An alternate function that is empty, too long, or has whitespace inside it."""


class InvalidPinTypeError(CatalogError):
    """A pin type that isn't one of the eight the domain knows."""


class InvalidVoltageError(CatalogError):
    """Text that can't be read as a voltage in volts, or a level beyond the ±1000 V cap."""


class InvalidFilterError(CatalogError):
    """A search filter the category's schema refuses: an unknown key, a kind mismatch, empty
    options, both bounds missing, a minimum above its maximum, an unreadable bound, or an
    attribute filter without a category. The message names the filter."""


class InvalidCursorError(CatalogError):
    """A paging cursor that doesn't decode, or that belongs to a different search."""


class InvalidSortError(CatalogError):
    """A sort a search can't honour: an attribute sort without a category, or on a non-number."""


class PinField(StrEnum):
    """The cell of a pin table a refusal is about — requirement 3.1's five.

    Here and not next to `Pin` because it belongs to the refusal: `InvalidPinoutError`
    carries one, the API answers it as text, and the editor marks that cell.
    """

    NUMBER = "number"
    LABEL = "label"
    TYPE = "type"
    FUNCTIONS = "functions"
    VOLTAGE = "voltage"


class InvalidPinoutError(CatalogError):
    """A pinout refused as a whole, or because of one of its rows (requirements 3.1-3.3).

    Every other catalog refusal is a sentence, and the part form finds the field it is about
    by the attribute name in it. A table of forty rows can't be read that way, so this one
    carries the row and the cell as data, which the API answers as a structured 422.
    """

    def __init__(self, message: str, row: int | None = None, field: PinField | None = None) -> None:
        # The row goes in front of the reason, so the message alone still says where to look.
        # Callers pass the bare reason: prefixing here is what keeps every row refusal alike.
        super().__init__(f"row {row}: {message}" if row is not None else message)
        self.row = row  # 1-based, as the editor numbers its rows
        self.field = field
