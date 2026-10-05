"""Search parts and count facets, both against the chosen category's resolved schema.

A search arrives as `PartSearch`: text, a category, raw filters that name attribute keys but
don't yet know what those keys mean, a sort, a direction and the page to read. Only the
category's resolved schema says whether a key exists and what kind it is, so `SearchParts`
loads that schema once and turns each `RawFilter` into a typed domain filter — refusing an
unknown key, a kind mismatch, empty options, a bad range, or an attribute filter with no
category, each 422 naming the filter (requirements 2.8, 2.9). Range bounds are read with the
attribute's own unit through `parse_si`, so `4k7` means 4700 here exactly as it does on a
part (requirement 2.2).

`CategoryFacets` counts over category, text and pin only: the attribute filters never narrow
the facets, so every option stays selectable as the owner picks one (requirement 5.2).
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from wiredex.catalog.application.attributes import resolve_schema
from wiredex.catalog.application.categories import UnitOfWorkFactory, load_category
from wiredex.catalog.application.ports import CatalogUnitOfWork, PartStock
from wiredex.catalog.domain.errors import InvalidFilterError, InvalidSortError
from wiredex.catalog.domain.notation import parse_si
from wiredex.catalog.domain.part import PartDefinition
from wiredex.catalog.domain.schema import AttributeDefinition, AttributeSchema
from wiredex.catalog.domain.search import (
    AllOf,
    HasPin,
    HasStock,
    InCategories,
    IsBool,
    ManufacturerContains,
    NumberBetween,
    OneOf,
    PartSort,
    SearchText,
    SortDirection,
    SortField,
    Spec,
    StockState,
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
from wiredex.shared_kernel.domain.paging import Page, PageRequest

# The first page of 50, what a search serves unless asked.
_FIRST_PAGE = PageRequest()
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
    """One request for a page of parts: what to match, how to order it, which page to read.

    Everything the web keeps in the address (design's Web), sent as one body. `manufacturer`
    is a fragment of the maker's name; `stock` asks for the parts in stock or out of it;
    `sort` is `newest`, `name` or `attribute:<key>`; `direction` is `asc` or `desc`; `page` is
    the page number and size, the first 50 unless asked. Nothing here is typed against a
    schema yet — that is `SearchParts`' job, and the only place that can read the schema.
    """

    text: str | None = None
    category_id: CategoryId | None = None
    exact_category: bool = False
    pin: str | None = None
    manufacturer: str | None = None
    stock: StockState | None = None
    filters: Sequence[RawFilter] = ()
    sort: str = "newest"
    direction: str = "desc"
    page: PageRequest = _FIRST_PAGE


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
    """A page of the parts a search matches, in its order, with how many match in all.

    Resolves the category's descendants and schema, turns the raw filters into typed ones
    against that schema, builds the `AllOf` spec and the sort, counts the matches, and asks
    `parts.search` for the page, the last one when the request lies past the end. One unit of
    work, no write: a search commits nothing.

    A stock filter first asks inventory, through `PartStock`, which parts hold some, in
    inventory's own transaction, closed before the catalog's opens; a search without one asks
    nothing of inventory.
    """

    def __init__(self, unit_of_work: UnitOfWorkFactory, part_stock: PartStock) -> None:
        self._unit_of_work = unit_of_work
        self._part_stock = part_stock

    async def __call__(self, workspace_id: WorkspaceId, search: PartSearch) -> Page[PartDefinition]:
        stock = await self._stock_spec(workspace_id, search.stock)
        async with self._unit_of_work(workspace_id) as work:
            schema = await _resolve_search_schema(work, search)
            spec = await _build_spec(work, search, schema, stock)
            sort = _build_sort(search, schema)
            total = await work.parts.count_matching(spec)
            served = search.page.within(total)
            rows = await work.parts.search(spec, sort, served)
            return Page(tuple(rows), total, served)

    async def _stock_spec(
        self, workspace_id: WorkspaceId, state: StockState | None
    ) -> HasStock | None:
        if state is None:
            return None
        return HasStock(state, await self._part_stock.stocked(workspace_id))


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
    work: CatalogUnitOfWork,
    search: PartSearch,
    schema: AttributeSchema | None,
    stock: HasStock | None,
) -> AllOf:
    """Every part of the search as one `AllOf`: category, text, pin, manufacturer, stock and
    the typed filters."""
    specs: list[Spec] = []
    if search.category_id is not None:
        specs.append(await _category_spec(work, search))
    if search.text is not None:
        specs.append(TextContains(SearchText(search.text)))
    if search.pin is not None:
        specs.append(HasPin(SearchText(search.pin)))
    if search.manufacturer is not None:
        specs.append(ManufacturerContains(SearchText(search.manufacturer)))
    if stock is not None:
        specs.append(stock)
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


def _read_key(text: str) -> AttributeKey:
    """The key a filter or sort names, as a 422 when the text could never be one.

    A key that isn't a slug is the owner's mistake, not a corrupt request, so it is a filter
    refusal (requirement 2.9), not a 500.
    """
    try:
        return AttributeKey(text)
    except ValueError as error:
        raise InvalidFilterError(f"filter {text!r}: {error}") from error
