"""Search parts and count facets, both against the chosen category's resolved schema.

A search arrives as `PartSearch`: text, a category, raw filters that name attribute keys but
don't yet know what those keys mean, a sort, a direction, a cursor and a page size. Only the
category's resolved schema says whether a key exists and what kind it is, so `SearchParts`
loads that schema once and turns each `RawFilter` into a typed domain filter — refusing an
unknown key, a kind mismatch, empty options, a bad range, or an attribute filter with no
category, each 422 naming the filter (requirements 2.8, 2.9). Range bounds are read with the
attribute's own unit through `parse_si`, so `4k7` means 4700 here exactly as it does on a
part (requirement 2.2).

`CategoryFacets` counts over category, text and pin only: the attribute filters never narrow
the facets, so every option stays selectable as the owner picks one (requirement 5.2).
"""

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import cast

from wiredex.catalog.application.attributes import resolve_schema
from wiredex.catalog.application.categories import UnitOfWorkFactory, load_category
from wiredex.catalog.application.ports import CatalogUnitOfWork, Page
from wiredex.catalog.domain.errors import InvalidFilterError, InvalidSortError
from wiredex.catalog.domain.notation import parse_si
from wiredex.catalog.domain.part import PartDefinition
from wiredex.catalog.domain.schema import AttributeDefinition, AttributeSchema
from wiredex.catalog.domain.search import (
    AllOf,
    HasPin,
    InCategories,
    IsBool,
    NumberBetween,
    OneOf,
    PartSort,
    SearchCursor,
    SearchText,
    SortDirection,
    SortField,
    Spec,
    TextAttributeContains,
    TextContains,
)
from wiredex.catalog.domain.values import (
    AttributeKey,
    AttributeKind,
    CategoryId,
    SiValue,
    WorkspaceId,
)

DEFAULT_SEARCH_LIMIT = 50
MAX_SEARCH_LIMIT = 100
# The sort token a `PartSearch` carries names an attribute after this prefix, `attribute:r`.
_ATTRIBUTE_SORT_PREFIX = "attribute:"


@dataclass(frozen=True, slots=True)
class RawFilter:
    """One filter as the API passes it on, untyped until the category's schema is known.

    The kind is read from which fields are set, the way the discriminated union on the wire
    is (design's HTTP API): a range has a `minimum` or a `maximum`, a set has `options`, a
    boolean has `value`, a text filter has `text`. `SearchParts` is what turns it into a
    typed domain filter, against the definition its `key` resolves to.
    """

    key: str
    minimum: str | None = None
    maximum: str | None = None
    options: Sequence[str] = ()
    value: bool | None = None
    text: str | None = None


@dataclass(frozen=True, slots=True)
class PartSearch:
    """One request for a page of parts: what to match, how to order it, where to carry on.

    Everything the web keeps in the address (design's Web), sent as one body. `sort` is
    `newest`, `name` or `attribute:<key>`; `direction` is `asc` or `desc`; `cursor` is the
    opaque token a previous page returned. Nothing here is typed against a schema yet — that
    is `SearchParts`' job, and the only place that can read the schema.
    """

    text: str | None = None
    category_id: CategoryId | None = None
    exact_category: bool = False
    pin: str | None = None
    filters: Sequence[RawFilter] = ()
    sort: str = "newest"
    direction: str = "desc"
    cursor: str | None = None
    limit: int = DEFAULT_SEARCH_LIMIT


@dataclass(frozen=True, slots=True)
class NumberRange:
    """The lowest and highest value some part holds for a number attribute (requirement 5.1)."""

    minimum: SiValue
    maximum: SiValue


@dataclass(frozen=True, slots=True)
class BoolCounts:
    """How many parts hold true and how many hold false for a boolean attribute."""

    true: int
    false: int


@dataclass(frozen=True, slots=True)
class Facets:
    """What a category's parts actually hold, per attribute of its resolved schema.

    `enums[key]` maps each option to how many parts have it, `bools[key]` the true and false
    counts, `numbers[key]` the range some part covers or `None` when no part has a value
    (requirement 5.3). Keyed by the attribute key so the web can line each facet up with the
    filter it belongs to.
    """

    enums: dict[AttributeKey, dict[str, int]] = field(default_factory=dict)
    bools: dict[AttributeKey, BoolCounts] = field(default_factory=dict)
    numbers: dict[AttributeKey, NumberRange | None] = field(default_factory=dict)


class SearchParts:
    """A page of the parts a search matches, ordered and continued from its cursor.

    Resolves the category's descendants and schema, turns the raw filters into typed ones
    against that schema, builds the `AllOf` spec, the sort and the cursor, and asks
    `parts.search` for one page. One read, no write: a search commits nothing.
    """

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(
        self, workspace_id: WorkspaceId, search: PartSearch
    ) -> Page[PartDefinition, SearchCursor]:
        async with self._unit_of_work(workspace_id) as work:
            schema = await _resolve_search_schema(work, search)
            spec = await _build_spec(work, search, schema)
            sort = _build_sort(search, schema)
            after = _build_cursor(search, spec, sort)
            return await work.parts.search(spec, sort, after, _capped_limit(search.limit))


class CategoryFacets:
    """The facet counts for a category, over its parts matching text and pin (requirement 5.1).

    The attribute filters are deliberately left out of the count (requirement 5.2), so this
    takes only the text and pin narrowing, never the filter list. One read, no write.
    """

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(
        self,
        workspace_id: WorkspaceId,
        category_id: CategoryId,
        text: str | None = None,
        pin: str | None = None,
    ) -> Facets:
        async with self._unit_of_work(workspace_id) as work:
            category = await load_category(work, category_id)
            schema = await resolve_schema(work, category)
            category_ids = await work.categories.descendants(category_id)
            specs: list[Spec] = [InCategories(frozenset(category_ids))]
            if text is not None:
                specs.append(TextContains(SearchText(text)))
            if pin is not None:
                specs.append(HasPin(SearchText(pin)))
            return await work.parts.facets(AllOf(tuple(specs)), schema)


async def _resolve_search_schema(
    work: CatalogUnitOfWork, search: PartSearch
) -> AttributeSchema | None:
    """The chosen category's resolved schema, or `None` when the search names no category.

    A search with no category is legitimate — text across the whole workspace (requirement
    1.4) — but it has no schema, so any attribute filter or attribute sort it carries is
    refused later against this `None`.
    """
    if search.category_id is None:
        return None
    category = await load_category(work, search.category_id)
    return await resolve_schema(work, category)


async def _build_spec(
    work: CatalogUnitOfWork, search: PartSearch, schema: AttributeSchema | None
) -> AllOf:
    """Every part of the search as one `AllOf`: category, text, pin and the typed filters."""
    specs: list[Spec] = []
    if search.category_id is not None:
        specs.append(await _category_spec(work, search))
    if search.text is not None:
        specs.append(TextContains(SearchText(search.text)))
    if search.pin is not None:
        specs.append(HasPin(SearchText(search.pin)))
    specs.extend(_typed_filter(raw, schema) for raw in search.filters)
    return AllOf(tuple(specs))


async def _category_spec(work: CatalogUnitOfWork, search: PartSearch) -> InCategories:
    """The chosen category alone, or it and its descendants unless asked for it alone (1.2)."""
    assert search.category_id is not None  # noqa: S101  guarded by the caller
    if search.exact_category:
        return InCategories(frozenset({search.category_id}))
    descendants = await work.categories.descendants(search.category_id)
    return InCategories(frozenset(descendants))


def _typed_filter(raw: RawFilter, schema: AttributeSchema | None) -> Spec:
    """One raw filter as the domain filter its resolved definition allows, or a 422.

    An attribute filter names a key, and only the category's schema says what the key means,
    so a filter with no category to resolve against is refused (requirement 2.8). A key the
    schema doesn't define, or one whose kind the filter's shape doesn't fit, is refused too,
    each naming the filter (requirement 2.9).
    """
    key = _read_key(raw.key)
    if schema is None:
        raise InvalidFilterError(
            f"filter {raw.key}: an attribute filter needs a category to read its key"
        )
    definition = schema.get(key)
    if definition is None:
        raise InvalidFilterError(f"filter {raw.key}: this category has no such attribute")
    builder = _BUILDERS[definition.kind]
    return builder(raw, definition)


def _range_filter(raw: RawFilter, definition: AttributeDefinition) -> NumberBetween:
    if raw.minimum is None and raw.maximum is None:
        raise InvalidFilterError(f"filter {definition.key}: a range needs a minimum or a maximum")
    minimum = _read_bound(raw.minimum, definition)
    maximum = _read_bound(raw.maximum, definition)
    # `NumberBetween` refuses a minimum above its maximum, naming the filter as this does.
    return NumberBetween(definition.key, minimum, maximum)


def _options_filter(raw: RawFilter, definition: AttributeDefinition) -> OneOf:
    if not raw.options:
        raise InvalidFilterError(f"filter {definition.key}: choose at least one option")
    # `OneOf` refuses an empty set; a set of options unknown to the enum simply matches
    # nothing, which is the honest answer when a stale option is asked for.
    return OneOf(definition.key, frozenset(raw.options))


def _bool_filter(raw: RawFilter, definition: AttributeDefinition) -> IsBool:
    if raw.value is None:
        raise InvalidFilterError(f"filter {definition.key}: a boolean filter needs true or false")
    return IsBool(definition.key, raw.value)


def _text_filter(raw: RawFilter, definition: AttributeDefinition) -> TextAttributeContains:
    if raw.text is None:
        raise InvalidFilterError(f"filter {definition.key}: a text filter needs a fragment")
    return TextAttributeContains(definition.key, SearchText(raw.text))


# One builder per kind, the same shape the SQL compiler will have: a new kind is a new entry.
_BUILDERS: dict[AttributeKind, Callable[[RawFilter, AttributeDefinition], Spec]] = {
    AttributeKind.NUMBER: _range_filter,
    AttributeKind.ENUM: _options_filter,
    AttributeKind.BOOL: _bool_filter,
    AttributeKind.TEXT: _text_filter,
}


def _read_bound(text: str | None, definition: AttributeDefinition) -> SiValue | None:
    """A range bound read with the attribute's unit, so `4k7` means 4700 (requirement 2.2).

    `None` is a bound left open. Whatever `parse_si` can't read — a stray unit, kelvin where
    kilo was meant — becomes a 422 naming the filter, since it is the owner's typing, not a
    corrupt request.
    """
    if text is None:
        return None
    try:
        return parse_si(text, definition.unit)
    except InvalidFilterError:
        raise
    except ValueError as error:
        raise InvalidFilterError(f"filter {definition.key}: {error}") from error


def _build_sort(search: PartSearch, schema: AttributeSchema | None) -> PartSort:
    """The sort a search names, refusing an attribute sort the schema can't honour (4.1).

    `newest` and `name` are always available. `attribute:<key>` needs a category, and the
    key has to resolve to a number attribute: the domain's `PartSort` refuses a
    contradictory shape, and this refuses a key that isn't a number the search can order by.
    """
    direction = _read_direction(search.direction)
    if search.sort.startswith(_ATTRIBUTE_SORT_PREFIX):
        key = _read_key(search.sort.removeprefix(_ATTRIBUTE_SORT_PREFIX))
        return _attribute_sort(key, direction, schema)
    return _column_sort(search.sort, direction)


def _column_sort(token: str, direction: SortDirection) -> PartSort:
    """A `newest` or `name` sort, refusing an attribute sort spelled without its key."""
    try:
        field_ = SortField(token)
    except ValueError as error:
        raise InvalidSortError(f"{token!r} is not a sort") from error
    if field_ is SortField.ATTRIBUTE:
        # Spelled bare, without a key after the prefix: there is nothing to sort by.
        raise InvalidSortError("an attribute sort needs the attribute to sort by")
    return PartSort(field_, direction)


def _attribute_sort(
    key: AttributeKey, direction: SortDirection, schema: AttributeSchema | None
) -> PartSort:
    """An `attribute:<key>` sort, refusing a key with no category or that isn't a number."""
    if schema is None:
        raise InvalidSortError("an attribute sort needs a category to read its key")
    definition = schema.get(key)
    if definition is None:
        raise InvalidSortError(f"{key} is not an attribute of this category")
    if definition.kind is not AttributeKind.NUMBER:
        raise InvalidSortError(f"{key} is a {definition.kind}, so a search can't sort by it")
    return PartSort.by_attribute(key, direction)


def _read_direction(direction: str) -> SortDirection:
    try:
        return SortDirection(direction)
    except ValueError as error:
        raise InvalidSortError(f"{direction!r} is not a sort direction") from error


def _build_cursor(search: PartSearch, spec: AllOf, sort: PartSort) -> SearchCursor | None:
    """The cursor a search carries, decoded against this search's fingerprint, or `None`.

    A cursor made for a different search has a different fingerprint and is refused
    (requirement 4.4); the first page carries no cursor at all.
    """
    if search.cursor is None:
        return None
    return SearchCursor.decode(search.cursor, fingerprint_of(spec, sort))


def fingerprint_of(spec: Spec, sort: PartSort) -> str:
    """A stable hash of what a search matches and how it is ordered.

    Two searches that select the same parts in the same order share a fingerprint, and any
    difference — a filter, the category, the sort — changes it, which is what lets a cursor
    tell its own search from another (requirement 4.4). The limit and the cursor are left
    out on purpose: the same search read a page at a time, with any page size, is one search.

    Public because building the next page's cursor and decoding the one that continues it
    are the same question asked from two places: `SearchParts` decodes here, and whatever
    serves `parts.search` — the SQL repository, the in-memory fake — stamps the cursor it
    returns with this, so a cursor and the search it belongs to always fingerprint alike.
    """
    material = f"{_spec_key(spec)}|{sort.token}|{sort.direction}"
    return hashlib.sha256(material.encode()).hexdigest()[:16]


def _spec_key(spec: Spec) -> str:
    """A canonical string for a spec: one small keyer per filter type, dispatched by class.

    A dict rather than a chain of branches, so adding a filter is one entry and no single
    function grows: the same reason the domain has one class per filter and the SQL compiler
    one case. Each keyer builds the key for its own type; sets are sorted inside it, so the
    same filters given in a different order fingerprint alike.
    """
    keyer = _SPEC_KEYS.get(type(spec))
    if keyer is None:  # pragma: no cover  a new filter class must be added to _SPEC_KEYS
        raise AssertionError(f"no fingerprint for {spec!r}")
    return keyer(spec)


def _all_of_key(spec: AllOf) -> str:
    return "AllOf(" + ",".join(sorted(_spec_key(inner) for inner in spec.specs)) + ")"


def _text_contains_key(spec: TextContains) -> str:
    return f"TextContains({spec.text.folded})"


def _in_categories_key(spec: InCategories) -> str:
    return "InCategories(" + ",".join(sorted(str(cid) for cid in spec.category_ids)) + ")"


def _number_between_key(spec: NumberBetween) -> str:
    return f"NumberBetween({spec.key},{_bound_key(spec.minimum)},{_bound_key(spec.maximum)})"


def _one_of_key(spec: OneOf) -> str:
    return f"OneOf({spec.key}," + ",".join(sorted(spec.options)) + ")"


def _is_bool_key(spec: IsBool) -> str:
    return f"IsBool({spec.key},{spec.value})"


def _text_attribute_key(spec: TextAttributeContains) -> str:
    return f"TextAttributeContains({spec.key},{spec.text.folded})"


def _has_pin_key(spec: HasPin) -> str:
    return f"HasPin({spec.name.folded})"


# One keyer per filter type, the shape `_BUILDERS` has. Each keyer's parameter is its own
# type; the values are erased to `Callable[[Spec], str]` here, and `_spec_key` only ever
# hands a keyer the type it was registered under, so the dispatch stays sound.
_SPEC_KEYS: dict[type, Callable[[Spec], str]] = {
    AllOf: cast("Callable[[Spec], str]", _all_of_key),
    TextContains: cast("Callable[[Spec], str]", _text_contains_key),
    InCategories: cast("Callable[[Spec], str]", _in_categories_key),
    NumberBetween: cast("Callable[[Spec], str]", _number_between_key),
    OneOf: cast("Callable[[Spec], str]", _one_of_key),
    IsBool: cast("Callable[[Spec], str]", _is_bool_key),
    TextAttributeContains: cast("Callable[[Spec], str]", _text_attribute_key),
    HasPin: cast("Callable[[Spec], str]", _has_pin_key),
}


def _bound_key(bound: SiValue | None) -> str:
    return "" if bound is None else str(bound)


def _read_key(text: str) -> AttributeKey:
    """The key a filter or sort names, as a 422 when the text could never be one.

    A key that isn't a slug is the owner's mistake, not a corrupt request, so it is a filter
    refusal (requirement 2.9), not a 500.
    """
    try:
        return AttributeKey(text)
    except ValueError as error:
        raise InvalidFilterError(f"filter {text!r}: {error}") from error


def _capped_limit(limit: int) -> int:
    """A page of at most 100 parts, 50 by default, at least 1 (requirement 4.5)."""
    return max(1, min(limit, MAX_SEARCH_LIMIT))
