from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from wiredex.catalog.domain.usage import PartUsage


class CatalogError(ValueError):
    """A value or change that breaks a catalog rule. The message is safe to show to users."""


class CategoryNotFoundError(CatalogError):
    pass


class AmbiguousCategoryError(CatalogError):
    """A category path that more than one category's path ends with. The message names each
    one's full path, so the owner can type enough of it to pick one."""


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


class PartInUseError(CatalogError):
    """A part a bill of materials names can't be deleted, or a revision would lose track of
    what it was built from (09's requirement 8.1). It carries the BOMs, so the refusal names
    the first few and counts the rest."""

    def __init__(self, message: str, usage: PartUsage) -> None:
        super().__init__(message)
        self.usage = usage


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


class DraftProblemKind(StrEnum):
    """Why one field of a part draft can't be defined as typed (design decision 17).

    Here and not next to `PartDrafts`, for the reason `PinField` is: `DraftRefusedError`
    carries these, and the domain can't import the application layer. Inventory's
    `ProblemCode` spells each one the same, so the web translates one code either way.
    """

    UNKNOWN_CATEGORY = "unknown_category"
    AMBIGUOUS_CATEGORY = "ambiguous_category"
    MISSING = "missing"  # no category, no name, or a required attribute left out
    INVALID = "invalid"  # a value its value object or validator refuses
    NOT_AN_ATTRIBUTE = "not_an_attribute"


@dataclass(frozen=True, slots=True)
class DraftProblem:
    """One field of a draft that can't be defined as typed, and a sentence saying why.

    `field` is `category`, `name`, `manufacturer`, `mpn`, `package` or an attribute key,
    which is how a quick-add marks the input and a sheet the column the problem is about.
    """

    field: str
    kind: DraftProblemKind
    message: str


class DraftRefusedError(CatalogError):
    """A part draft refused whole, carrying every problem found in it (requirements 1.5, 5.5).

    Every problem, not the first: the owner fixes a quick-add or a sheet row in one pass.
    """

    def __init__(self, problems: Sequence[DraftProblem]) -> None:
        reasons = "; ".join(problem.message for problem in problems)
        super().__init__(f"the part can't be defined as it is: {reasons}")
        self.problems = tuple(problems)
