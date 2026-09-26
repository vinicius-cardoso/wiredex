"""A search as composable filters, each one a small immutable value that matches one part.

The Specification pattern `docs/architecture.md` names: the domain holds plain filter
objects that know how to evaluate a single part (`matches`), which the in-memory fakes use;
the infrastructure turns the same objects into SQL, one case per filter (task 6). Domain
code stays free of SQLAlchemy, and a new filter is a new class plus a new compile case.

Every filter reads a value only when it is the kind that filter is about — a number filter
reads `SiValue`, a text filter reads `str` — so a part holding the wrong kind after a schema
change drops out of that filter instead of matching by accident or failing (requirement 2.7).
"""

import base64
import binascii
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from wiredex.catalog.domain.errors import (
    CatalogError,
    InvalidCursorError,
    InvalidFilterError,
    InvalidSortError,
)
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
class AllOf:
    """Every filter has to hold. An empty `AllOf` matches every part (requirements 2.6, 3.2)."""

    specs: tuple[Spec, ...]

    def matches(self, part: PartDefinition, pins: Pinout) -> bool:
        return all(spec.matches(part, pins) for spec in self.specs)


# --- Sorting and the cursor ------------------------------------------------------------
#
# A page is ordered by a sort field, ties broken by id, and continued with a keyset cursor:
# an opaque token carrying where the last page ended and a fingerprint of the search it
# belongs to. The infrastructure (task 6) turns the sort and the cursor into the ORDER BY
# and the keyset WHERE; here the domain owns the token's shape and its two refusals — a
# token that doesn't decode, and one whose fingerprint is another search's.


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

    @property
    def token(self) -> str:
        """The sort as one string, `newest`, `name` or `attribute:<key>`, as a cursor stores it."""
        if self.field is SortField.ATTRIBUTE:
            return f"{SortField.ATTRIBUTE}:{self.key}"
        return str(self.field)


def _parse_sort(token: str, direction: str) -> PartSort:
    """A sort back from its stored `field`/`attribute:<key>` token and direction, or a refusal.

    Only for decoding a cursor: a token the domain wrote, so a shape it doesn't recognise is
    a corrupt cursor, not a user's mistake.
    """
    try:
        way = SortDirection(direction)
    except ValueError as error:
        raise InvalidCursorError("the cursor's direction is not one this search knows") from error
    prefix, _, rest = token.partition(":")
    try:
        field = SortField(prefix)
    except ValueError as error:
        raise InvalidCursorError("the cursor's sort is not one this search knows") from error
    try:
        if field is SortField.ATTRIBUTE:
            return PartSort(field, way, AttributeKey(rest))
        if rest:
            raise InvalidCursorError(f"a {field} sort takes no attribute")
        return PartSort(field, way)
    except CatalogError as error:
        raise InvalidCursorError("the cursor's sort is not one this search knows") from error


@dataclass(frozen=True, slots=True)
class SearchCursor:
    """Where the last page ended, so the next one continues without repeating or skipping.

    The keyset the infrastructure pages by: the sort, the last row's sort value (as the text
    that crosses the wire, `None` for a part that had no value, which sorts last), and the
    last row's id to break ties on the sort value. It carries a fingerprint of the search it
    was made for, so replaying it against a different search is a refusal (requirement 4.4)
    rather than a page that quietly belongs to the wrong query.
    """

    sort: PartSort
    last_value: str | None
    last_id: PartDefinitionId
    fingerprint: str

    def encode(self) -> str:
        """The cursor as one opaque base64url token, the form the client sends back untouched."""
        payload = {
            "s": self.sort.token,
            "d": str(self.sort.direction),
            "v": self.last_value,
            "i": str(self.last_id),
            "f": self.fingerprint,
        }
        raw = json.dumps(payload, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode()

    @classmethod
    def decode(cls, token: str, fingerprint: str) -> SearchCursor:
        """The cursor a token carries, refusing one that doesn't decode or is another search's.

        The fingerprint is the current search's: a cursor whose own fingerprint differs was
        made for a different search, and continuing it would return a page of the wrong query
        (requirement 4.4). Every way the token can be malformed — bad base64, bad JSON, a
        missing field, an id that isn't a UUID, an unknown sort — is the same refusal, since
        a client never builds a cursor, it only echoes one the API gave it.
        """
        try:
            raw = base64.urlsafe_b64decode(token.encode())
            payload = json.loads(raw)
            sort = _parse_sort(payload["s"], payload["d"])
            last_value = payload["v"]
            last_id = PartDefinitionId(UUID(payload["i"]))
            carried = payload["f"]
        except InvalidCursorError:
            raise
        except (ValueError, TypeError, KeyError, binascii.Error) as error:
            raise InvalidCursorError("this cursor can't be read") from error
        if not isinstance(last_value, str) and last_value is not None:
            raise InvalidCursorError("this cursor can't be read")
        if not isinstance(carried, str) or carried != fingerprint:
            raise InvalidCursorError("this cursor belongs to a different search")
        return cls(sort, last_value, last_id, carried)
