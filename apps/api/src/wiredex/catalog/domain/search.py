"""A search as composable filters, each one a small immutable value that matches one part.

The Specification pattern `docs/architecture.md` names: the domain holds plain filter
objects that know how to evaluate a single part (`matches`), which the in-memory fakes use;
the infrastructure turns the same objects into SQL, one case per filter (task 6). Domain
code stays free of SQLAlchemy, and a new filter is a new class plus a new compile case.

Every filter reads a value only when it is the kind that filter is about — a number filter
reads `SiValue`, a text filter reads `str` — so a part holding the wrong kind after a schema
change drops out of that filter instead of matching by accident or failing (requirement 2.7).
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from wiredex.catalog.domain.errors import InvalidFilterError, InvalidSortError
from wiredex.catalog.domain.part import PartDefinition
from wiredex.catalog.domain.pinout import Pinout
from wiredex.catalog.domain.values import AttributeKey, CategoryId, PartDefinitionId, SiValue

MAX_SEARCH_TEXT_LENGTH = 80


@dataclass(frozen=True, slots=True)
class SearchText:
    """A fragment or name to search for: trimmed, whitespace collapsed, 1 to 80 characters.

    Case-folded once here, so every `matches` compares folded text and no filter has to
    remember to lower-case (requirements 1.1, 2.5, 3.1).
    """

    value: str

    def __post_init__(self) -> None:
        collapsed = " ".join(self.value.split())
        if not 1 <= len(collapsed) <= MAX_SEARCH_TEXT_LENGTH:
            raise InvalidFilterError(
                f"search text needs between 1 and {MAX_SEARCH_TEXT_LENGTH} characters"
            )
        object.__setattr__(self, "value", collapsed)

    @property
    def folded(self) -> str:
        """The value lower-cased, for the case-insensitive comparisons every text filter does."""
        return self.value.casefold()

    def __str__(self) -> str:
        return self.value


@runtime_checkable
class Spec(Protocol):
    """A filter that can say whether one part, with its pins, belongs in the results."""

    def matches(self, part: PartDefinition, pins: Pinout) -> bool: ...


def _contains(fragment: SearchText, *fields: object) -> bool:
    """Whether any of the given fields, as text, contains the fragment, ignoring case."""
    needle = fragment.folded
    return any(field is not None and needle in str(field).casefold() for field in fields)


@dataclass(frozen=True, slots=True)
class TextContains:
    """Matches parts whose name, manufacturer, MPN or package holds the text (requirement 1.1)."""

    text: SearchText

    def matches(self, part: PartDefinition, pins: Pinout) -> bool:  # noqa: ARG002  the Spec shape
        return _contains(self.text, part.name, part.manufacturer, part.mpn, part.package)


@dataclass(frozen=True, slots=True)
class InCategories:
    """Matches parts in the chosen category, or in it and its descendants (requirement 1.2)."""

    category_ids: frozenset[CategoryId]

    def matches(self, part: PartDefinition, pins: Pinout) -> bool:  # noqa: ARG002  the Spec shape
        return part.category_id in self.category_ids


@dataclass(frozen=True, slots=True)
class NumberBetween:
    """Matches parts whose number value lies within the bounds, both included (requirement 2.1).

    At least one bound is given and, when both are, the minimum is not above the maximum;
    building one any other way is a refusal the application raises. A part whose value is
    missing or not a number drops out (requirement 2.7).
    """

    key: AttributeKey
    minimum: SiValue | None
    maximum: SiValue | None

    def __post_init__(self) -> None:
        if self.minimum is None and self.maximum is None:
            raise InvalidFilterError(
                f"filter {self.key}: a range needs a minimum, a maximum or both"
            )
        if (
            self.minimum is not None
            and self.maximum is not None
            and self.minimum.value > self.maximum.value
        ):
            raise InvalidFilterError(f"filter {self.key}: the minimum is above the maximum")

    def matches(self, part: PartDefinition, pins: Pinout) -> bool:  # noqa: ARG002  the Spec shape
        value = part.attributes.get(self.key)
        if not isinstance(value, SiValue):
            return False
        if self.minimum is not None and value.value < self.minimum.value:
            return False
        return self.maximum is None or value.value <= self.maximum.value


@dataclass(frozen=True, slots=True)
class OneOf:
    """Matches parts whose enum value is any of the chosen options (requirement 2.3)."""

    key: AttributeKey
    options: frozenset[str]

    def __post_init__(self) -> None:
        if not self.options:
            raise InvalidFilterError(f"filter {self.key}: choose at least one option")

    def matches(self, part: PartDefinition, pins: Pinout) -> bool:  # noqa: ARG002  the Spec shape
        value = part.attributes.get(self.key)
        return isinstance(value, str) and value in self.options


@dataclass(frozen=True, slots=True)
class IsBool:
    """Matches parts whose boolean value is the one asked for (requirement 2.4)."""

    key: AttributeKey
    value: bool

    def matches(self, part: PartDefinition, pins: Pinout) -> bool:  # noqa: ARG002  the Spec shape
        stored = part.attributes.get(self.key)
        # `is`, not `==`: a stored value of the wrong kind must not match through truthiness.
        return stored is self.value


@dataclass(frozen=True, slots=True)
class TextAttributeContains:
    """Matches parts whose text attribute contains the fragment, ignoring case (requirement 2.5)."""

    key: AttributeKey
    text: SearchText

    def matches(self, part: PartDefinition, pins: Pinout) -> bool:  # noqa: ARG002  the Spec shape
        value = part.attributes.get(self.key)
        return isinstance(value, str) and self.text.folded in value.casefold()


@dataclass(frozen=True, slots=True)
class HasPin:
    """Matches parts with a pin whose label or one of its functions equals the name, ignoring
    case (requirement 3.1)."""

    name: SearchText

    def matches(self, part: PartDefinition, pins: Pinout) -> bool:  # noqa: ARG002  the Spec shape
        wanted = self.name.folded
        return any(
            str(pin.label).casefold() == wanted
            or any(str(function).casefold() == wanted for function in pin.functions)
            for pin in pins
        )


@dataclass(frozen=True, slots=True)
class ManufacturerContains:
    """Matches parts whose manufacturer holds the text, ignoring case; a part with no
    manufacturer never does."""

    text: SearchText

    def matches(self, part: PartDefinition, pins: Pinout) -> bool:  # noqa: ARG002  the Spec shape
        return _contains(self.text, part.manufacturer)


class StockState(StrEnum):
    """What the parts list's stock filter asks for: the parts with stock on hand, or those
    without any."""

    IN_STOCK = "in_stock"
    OUT_OF_STOCK = "out_of_stock"


@dataclass(frozen=True, slots=True)
class HasStock:
    """Matches the parts in stock, or out of it, against the parts inventory says hold some.

    The catalog doesn't keep stock, so the set is asked of inventory before the search runs
    and the filter carries it.
    """

    state: StockState
    stocked: frozenset[PartDefinitionId]

    def matches(self, part: PartDefinition, pins: Pinout) -> bool:  # noqa: ARG002  the Spec shape
        held = part.id in self.stocked
        return held if self.state is StockState.IN_STOCK else not held


@dataclass(frozen=True, slots=True)
class AllOf:
    """Every filter has to hold. An empty `AllOf` matches every part (requirements 2.6, 3.2)."""

    specs: tuple[Spec, ...]

    def matches(self, part: PartDefinition, pins: Pinout) -> bool:
        return all(spec.matches(part, pins) for spec in self.specs)


# --- Sorting ---------------------------------------------------------------------------
#
# A search is ordered by a sort field, ties broken by id, so the order is total and a page
# read by number neither repeats nor skips a part. The infrastructure turns the sort into
# the ORDER BY; the in-memory fakes sort the same way in Python.


class SortField(StrEnum):
    """What a page is ordered by: newest first (the default), by name, or by a number attribute."""

    NEWEST = "newest"
    NAME = "name"
    ATTRIBUTE = "attribute"


class SortDirection(StrEnum):
    """Ascending or descending. Newest defaults to descending; the smallest capacitor, ascending."""

    ASC = "asc"
    DESC = "desc"


@dataclass(frozen=True, slots=True)
class PartSort:
    """How a search is ordered: a field, a direction, and a key when the field is an attribute.

    An attribute sort names the number attribute to order by; the other two fields name a
    column of the part itself and carry no key. Building an attribute sort without a key, or
    either other sort with one, is a contradiction the domain refuses here so no caller has
    to (requirement 4.1). Validating the key against the category's schema — that it exists
    and is a number — is the application's job (task 3), which alone can read the schema.
    """

    field: SortField
    direction: SortDirection = SortDirection.DESC
    key: AttributeKey | None = None

    def __post_init__(self) -> None:
        if self.field is SortField.ATTRIBUTE and self.key is None:
            raise InvalidSortError("an attribute sort needs the attribute to sort by")
        if self.field is not SortField.ATTRIBUTE and self.key is not None:
            raise InvalidSortError(f"a {self.field} sort takes no attribute")

    @classmethod
    def newest(cls, direction: SortDirection = SortDirection.DESC) -> PartSort:
        return cls(SortField.NEWEST, direction)

    @classmethod
    def by_name(cls, direction: SortDirection = SortDirection.ASC) -> PartSort:
        return cls(SortField.NAME, direction)

    @classmethod
    def by_attribute(
        cls, key: AttributeKey, direction: SortDirection = SortDirection.ASC
    ) -> PartSort:
        return cls(SortField.ATTRIBUTE, direction, key)
