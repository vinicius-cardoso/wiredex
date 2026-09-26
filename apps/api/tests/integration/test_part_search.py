"""The SQL compiler and `SqlPartDefinitions.search` against a real PostgreSQL.

What only the database can answer: that each filter compiles to a predicate Postgres agrees
with, that `%` and `_` in searched text are characters and not wildcards (requirement 1.5),
that parts without a sort value come last in either direction (requirement 4.2), that a page
costs one query however many filters it carries (requirement 7.3), and that the trigram and
attribute indexes are the ones a search uses (requirements 7.1, 7.2).

The two properties live here because both walk the real query: Property 1 pages a search
through the database and through the domain's `matches` and asserts the same ids in the same
order (requirement 7.4); Property 2 follows the cursors to the end and asserts each part comes
back exactly once (requirement 4.3). Their `max_examples` is small on purpose — every example
seeds and searches Postgres.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from functools import cmp_to_key
from uuid import uuid7

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from support.catalog import _ordering
from support.sql import counting
from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.settings import Environment, Settings
from wiredex.catalog.application.ports import Page
from wiredex.catalog.application.search import BoolCounts, Facets, NumberRange
from wiredex.catalog.domain.category import Category
from wiredex.catalog.domain.part import PartDefinition, PartDetails
from wiredex.catalog.domain.pinout import Pinout, RawPin
from wiredex.catalog.domain.schema import (
    AttributeDefinition,
    AttributeSchema,
    AttributeValues,
)
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
    Spec,
    TextAttributeContains,
    TextContains,
)
from wiredex.catalog.domain.values import (
    AttributeDefinitionId,
    AttributeKey,
    AttributeKind,
    AttributeLabel,
    CategoryId,
    CategoryName,
    Manufacturer,
    Mpn,
    PartDefinitionId,
    PartName,
    SiValue,
    Unit,
    WorkspaceId,
)
from wiredex.catalog.infrastructure.unit_of_work import SqlCatalogUnitOfWork

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

NOW = datetime(2026, 9, 25, 10, tzinfo=UTC)
BENCH = WorkspaceId(uuid7())
OHM = Unit("Ω")
RESISTANCE = AttributeKey("resistance")
MOUNTING = AttributeKey("mounting")
ROHS = AttributeKey("rohs")
NOTES = AttributeKey("notes")
CATALOG_TABLES = "pins, part_definitions, attribute_definitions, categories"


@pytest.fixture
async def engine(migrated_database_url: str) -> AsyncIterator[AsyncEngine]:
    # The API's engine, so a Decimal reaches JSONB as an exact number the `::numeric` cast
    # and the `@>` containment read back (ADR 0005).
    settings_ = Settings(
        environment=Environment.TEST, database_url=SecretStr(migrated_database_url)
    )
    engine = create_engine(settings_)
    yield engine
    async with engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE {CATALOG_TABLES} CASCADE"))
    await engine.dispose()


def catalog(engine: AsyncEngine, workspace_id: WorkspaceId = BENCH) -> SqlCatalogUnitOfWork:
    return SqlCatalogUnitOfWork(create_session_factory(engine), workspace_id)


async def _truncate(engine: AsyncEngine) -> None:
    """Empties the catalog tables between property examples, which share one engine fixture.

    Hypothesis runs many examples inside one test, so the function-scoped `engine` teardown
    doesn't fire between them: without this each example's parts would pile up and a second
    root category of the same name would trip the unique constraint.
    """
    async with engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE {CATALOG_TABLES} CASCADE"))


def a_category(name: str = "Resistors", parent: Category | None = None) -> Category:
    return Category(
        CategoryId(uuid7()),
        BENCH,
        None if parent is None else parent.id,
        CategoryName(name),
        NOW,
    )


def a_part(
    category: Category,
    name: str = "R 4k7 0805",
    *,
    details: PartDetails | None = None,
    attributes: dict[AttributeKey, object] | None = None,
) -> PartDefinition:
    return PartDefinition.define(
        PartDefinitionId(uuid7()),
        category,
        PartDetails(PartName(name)) if details is None else details,
        AttributeValues({} if attributes is None else attributes),
        NOW,
    )


async def save(
    engine: AsyncEngine,
    category: Category,
    parts: list[PartDefinition],
    pinouts: dict[PartDefinitionId, Pinout] | None = None,
) -> None:
    """Seeds one category and its parts, with any pinouts, through the repositories."""
    async with catalog(engine) as work:
        await work.categories.add(category)
        for part in parts:
            await work.parts.add(part)
        for part_id, pinout in (pinouts or {}).items():
            await work.pinouts.replace(part_id, pinout)
        await work.commit()


async def ids_of(
    engine: AsyncEngine, spec: Spec, sort: PartSort | None = None
) -> list[PartDefinitionId]:
    """The ids a one-page search returns, in order — a page big enough to hold them all."""
    async with catalog(engine) as work:
        page = await work.parts.search(spec, sort or PartSort.newest(), None, limit=1000)
    return [part.id for part in page.items]


# --- Each filter compiles to a predicate Postgres agrees with --------------------------


async def test_text_contains_matches_the_identifying_fields(engine: AsyncEngine) -> None:
    resistors = a_category()
    named = a_part(resistors, "SDA level shifter")
    by_mpn = a_part(resistors, "Sensor", details=PartDetails(PartName("Sensor"), mpn=Mpn("BME280")))
    other = a_part(resistors, "Capacitor")
    await save(engine, resistors, [named, by_mpn, other])

    found = await ids_of(engine, TextContains(SearchText("sensor")))
    by_number = await ids_of(engine, TextContains(SearchText("bme")))

    assert set(found) == {by_mpn.id}
    assert set(by_number) == {by_mpn.id}


async def test_a_wildcard_in_the_text_is_a_character(engine: AsyncEngine) -> None:
    # Requirement 1.5: `%` and `_` match themselves, never "any run" or "any character".
    resistors = a_category()
    literal_percent = a_part(resistors, "R 4k7 5%")
    literal_underscore = a_part(resistors, "part_one")
    plain = a_part(resistors, "R 10k 1")
    await save(engine, resistors, [literal_percent, literal_underscore, plain])

    percent = await ids_of(engine, TextContains(SearchText("5%")))
    underscore = await ids_of(engine, TextContains(SearchText("part_one")))

    assert set(percent) == {literal_percent.id}
    # `part_one` as a literal matches only itself, not "partXone" — there is no such part,
    # and `plain` (which an unescaped `_` could never reach) stays out regardless.
    assert set(underscore) == {literal_underscore.id}


async def test_in_categories_matches_the_chosen_set(engine: AsyncEngine) -> None:
    resistors = a_category()
    mine = a_part(resistors, "R 4k7")
    await save(engine, resistors, [mine])

    inside = await ids_of(engine, InCategories(frozenset({resistors.id})))
    outside = await ids_of(engine, InCategories(frozenset({CategoryId(uuid7())})))

    assert set(inside) == {mine.id}
    assert outside == []


async def test_number_between_includes_its_bounds_and_drops_wrong_kinds(
    engine: AsyncEngine,
) -> None:
    resistors = a_category()
    low = a_part(resistors, "220R", attributes={RESISTANCE: SiValue(Decimal("220"))})
    mid = a_part(resistors, "4k7", attributes={RESISTANCE: SiValue(Decimal("4700"))})
    high = a_part(resistors, "100k", attributes={RESISTANCE: SiValue(Decimal("100000"))})
    missing = a_part(resistors, "no value")
    wrong = a_part(resistors, "text value", attributes={RESISTANCE: "not a number"})
    await save(engine, resistors, [low, mid, high, missing, wrong])

    between = await ids_of(
        engine,
        NumberBetween(RESISTANCE, SiValue(Decimal("1000")), SiValue(Decimal("10000"))),
    )
    at_least = await ids_of(engine, NumberBetween(RESISTANCE, SiValue(Decimal("4700")), None))
    at_most = await ids_of(engine, NumberBetween(RESISTANCE, None, SiValue(Decimal("4700"))))

    assert set(between) == {mid.id}
    # 4700 is included at both ends; the missing and wrong-kind parts never appear (2.7).
    assert set(at_least) == {mid.id, high.id}
    assert set(at_most) == {low.id, mid.id}


async def test_one_of_matches_any_chosen_option(engine: AsyncEngine) -> None:
    resistors = a_category()
    smd = a_part(resistors, "smd part", attributes={MOUNTING: "smd"})
    axial = a_part(resistors, "axial part", attributes={MOUNTING: "axial"})
    wrong = a_part(resistors, "number", attributes={MOUNTING: SiValue(Decimal("1"))})
    await save(engine, resistors, [smd, axial, wrong])

    found = await ids_of(engine, OneOf(MOUNTING, frozenset({"smd", "through-hole"})))

    assert set(found) == {smd.id}


async def test_is_bool_matches_the_stored_boolean(engine: AsyncEngine) -> None:
    resistors = a_category()
    compliant = a_part(resistors, "rohs yes", attributes={ROHS: True})
    not_compliant = a_part(resistors, "rohs no", attributes={ROHS: False})
    # A number 1 under the key must not read as true: `@>` compares the JSON boolean.
    number = a_part(resistors, "number one", attributes={ROHS: SiValue(Decimal("1"))})
    await save(engine, resistors, [compliant, not_compliant, number])

    truthy = await ids_of(engine, IsBool(ROHS, value=True))
    falsy = await ids_of(engine, IsBool(ROHS, value=False))

    assert set(truthy) == {compliant.id}
    assert set(falsy) == {not_compliant.id}


async def test_text_attribute_contains_matches_a_string_value(engine: AsyncEngine) -> None:
    resistors = a_category()
    noted = a_part(resistors, "noted", attributes={NOTES: "Pulled from a DEV board"})
    other = a_part(resistors, "other", attributes={NOTES: "spare"})
    number = a_part(resistors, "number", attributes={NOTES: SiValue(Decimal("42"))})
    await save(engine, resistors, [noted, other, number])

    found = await ids_of(engine, TextAttributeContains(NOTES, SearchText("dev board")))

    # Case-insensitive, and the number under the key is not fed to `->>` as a match.
    assert set(found) == {noted.id}


async def test_has_pin_matches_label_or_function_ignoring_case(engine: AsyncEngine) -> None:
    resistors = a_category()
    by_label = a_part(resistors, "has SDA label")
    by_function = a_part(resistors, "has SDA function")
    neither = a_part(resistors, "no i2c")
    await save(
        engine,
        resistors,
        [by_label, by_function, neither],
        pinouts={
            by_label.id: Pinout.parse([RawPin(number="1", label="SDA", type="io")]),
            by_function.id: Pinout.parse(
                [RawPin(number="1", label="GPIO21", type="io", functions=["SDA", "SCL"])]
            ),
            neither.id: Pinout.parse([RawPin(number="1", label="GND", type="ground")]),
        },
    )

    found = await ids_of(engine, HasPin(SearchText("sda")))

    assert set(found) == {by_label.id, by_function.id}


async def test_an_empty_all_of_matches_every_part(engine: AsyncEngine) -> None:
    resistors = a_category()
    parts = [a_part(resistors, f"P{n}") for n in range(3)]
    await save(engine, resistors, parts)

    found = await ids_of(engine, AllOf(()))

    assert set(found) == {part.id for part in parts}


async def test_all_of_requires_every_filter(engine: AsyncEngine) -> None:
    resistors = a_category()
    both = a_part(
        resistors, "smd 4k7", attributes={RESISTANCE: SiValue(Decimal("4700")), MOUNTING: "smd"}
    )
    only_number = a_part(
        resistors, "4k7 axial", attributes={RESISTANCE: SiValue(Decimal("4700")), MOUNTING: "axial"}
    )
    only_mount = a_part(
        resistors, "smd 100k", attributes={RESISTANCE: SiValue(Decimal("100000")), MOUNTING: "smd"}
    )
    await save(engine, resistors, [both, only_number, only_mount])

    spec = AllOf(
        (
            InCategories(frozenset({resistors.id})),
            NumberBetween(RESISTANCE, SiValue(Decimal("1000")), SiValue(Decimal("10000"))),
            OneOf(MOUNTING, frozenset({"smd"})),
        )
    )
    found = await ids_of(engine, spec)

    assert set(found) == {both.id}


# --- Sorting: nulls last, both directions ----------------------------------------------


async def test_an_attribute_sort_puts_valueless_parts_last_both_ways(engine: AsyncEngine) -> None:
    # Requirement 4.2: a part with no number for the sort key comes last, ascending or not.
    resistors = a_category()
    low = a_part(resistors, "220R", attributes={RESISTANCE: SiValue(Decimal("220"))})
    high = a_part(resistors, "100k", attributes={RESISTANCE: SiValue(Decimal("100000"))})
    missing = a_part(resistors, "no value")
    await save(engine, resistors, [low, high, missing])

    spec = InCategories(frozenset({resistors.id}))
    ascending = await ids_of(engine, spec, PartSort.by_attribute(RESISTANCE, SortDirection.ASC))
    descending = await ids_of(engine, spec, PartSort.by_attribute(RESISTANCE, SortDirection.DESC))

    assert ascending == [low.id, high.id, missing.id]
    assert descending == [high.id, low.id, missing.id]


# --- Paging each sort, a page at a time ------------------------------------------------


async def test_paging_by_name_follows_the_cursor(engine: AsyncEngine) -> None:
    # A name sort paged one at a time: the cursor carries the folded name and the id, and the
    # pages together are the whole search in order, nothing repeated or skipped (requirement 4.3).
    resistors = a_category()
    parts = [a_part(resistors, name) for name in ("Cap", "bead", "Diode", "amp")]
    await save(engine, resistors, parts)
    spec = InCategories(frozenset({resistors.id}))
    sort = PartSort.by_name(SortDirection.ASC)

    paged = await _all_pages(engine, spec, sort, page_size=1)
    whole = await ids_of(engine, spec, sort)

    # Folded, so "amp" and "bead" come before "Cap" and "Diode".
    assert [str(p.name) for p in sorted(parts, key=lambda p: p.name.value.casefold())] == [
        "amp",
        "bead",
        "Cap",
        "Diode",
    ]
    assert paged == whole


async def test_paging_by_an_attribute_follows_the_cursor_with_nulls_last(
    engine: AsyncEngine,
) -> None:
    # An attribute sort paged one at a time: the cursor carries the number (or none for a
    # value-less part) and the id, so a part with no value pages last and nothing repeats.
    resistors = a_category()
    low = a_part(resistors, "220R", attributes={RESISTANCE: SiValue(Decimal("220"))})
    mid = a_part(resistors, "4k7", attributes={RESISTANCE: SiValue(Decimal("4700"))})
    high = a_part(resistors, "100k", attributes={RESISTANCE: SiValue(Decimal("100000"))})
    missing = a_part(resistors, "no value")
    await save(engine, resistors, [low, mid, high, missing])
    spec = InCategories(frozenset({resistors.id}))
    sort = PartSort.by_attribute(RESISTANCE, SortDirection.ASC)

    paged = await _all_pages(engine, spec, sort, page_size=1)

    # Ascending by resistance, the value-less part last, and every part exactly once.
    assert paged == [low.id, mid.id, high.id, missing.id]


async def test_paging_by_newest_follows_the_cursor(engine: AsyncEngine) -> None:
    # The default sort paged one at a time: newest first, the cursor an id, every part once.
    resistors = a_category()
    parts = [a_part(resistors, f"P{n}") for n in range(4)]
    await save(engine, resistors, parts)
    spec = InCategories(frozenset({resistors.id}))
    sort = PartSort.newest(SortDirection.DESC)

    paged = await _all_pages(engine, spec, sort, page_size=1)
    whole = await ids_of(engine, spec, sort)

    # UUIDv7 ids ascend with creation, so newest-first is the reverse of the insert order.
    assert paged == [part.id for part in reversed(parts)]
    assert paged == whole


# --- One query per page ----------------------------------------------------------------


async def test_a_page_costs_one_query_whatever_the_filters(engine: AsyncEngine) -> None:
    # Requirement 7.3: text, category, a range, an enum and a pin all fold into one statement.
    resistors = a_category()
    parts = [
        a_part(resistors, f"R {n}", attributes={RESISTANCE: SiValue(Decimal(n)), MOUNTING: "smd"})
        for n in (1000, 2000, 3000)
    ]
    await save(
        engine,
        resistors,
        parts,
        pinouts={parts[0].id: Pinout.parse([RawPin(number="1", label="SDA", type="io")])},
    )
    spec = AllOf(
        (
            InCategories(frozenset({resistors.id})),
            TextContains(SearchText("R")),
            NumberBetween(RESISTANCE, SiValue(Decimal("500")), SiValue(Decimal("5000"))),
            OneOf(MOUNTING, frozenset({"smd"})),
            HasPin(SearchText("sda")),
        )
    )

    async with catalog(engine) as work:
        with counting(engine) as statements:
            await work.parts.search(spec, PartSort.newest(), None, limit=50)

    assert len(statements) == 1, statements


# --- The indexes a search uses ---------------------------------------------------------


async def _explain(engine: AsyncEngine, sql: str) -> str:
    """The plan for a query, with the sequential scan disabled for the statement.

    A throwaway test table is small enough that the planner reads every row rather than an
    index, whatever indexes exist. Turning the sequential scan off for the one statement is
    what makes the plan show which index *can* serve the query — the promise requirements 7.1
    and 7.2 make — instead of which the planner picks at a handful of rows.
    """
    async with engine.begin() as connection:
        await connection.execute(text("SET LOCAL enable_seqscan = off"))
        rows = await connection.execute(text(f"EXPLAIN {sql}"))
        return "\n".join(rows.scalars())


async def _seed_many(engine: AsyncEngine, category: Category, count: int) -> None:
    """A seeded table for the planner to explain a search over."""
    parts = [
        a_part(
            category,
            f"Resistor {n} SDA",
            details=PartDetails(PartName(f"Resistor {n} SDA"), manufacturer=Manufacturer("Vishay")),
            attributes={RESISTANCE: SiValue(Decimal(n)), MOUNTING: "smd"},
        )
        for n in range(count)
    ]
    async with catalog(engine) as work:
        await work.categories.add(category)
        for part in parts:
            await work.parts.add(part)
        await work.commit()
    async with engine.begin() as connection:
        await connection.execute(text("ANALYZE part_definitions"))


async def test_a_text_search_uses_a_trigram_index(engine: AsyncEngine) -> None:
    # Requirement 7.1: an ILIKE over the identifying text can ride the trigram GIN index,
    # not a scan of every part.
    resistors = a_category()
    await _seed_many(engine, resistors, 200)

    plan = await _explain(
        engine, "SELECT id FROM part_definitions WHERE name ILIKE '%Resistor 1337%'"
    )

    assert "ix_part_definitions_name_trgm" in plan, plan


async def test_an_attribute_filter_uses_the_gin_index(engine: AsyncEngine) -> None:
    # Requirement 7.2: an enum `@>` containment can ride the attributes' GIN index.
    resistors = a_category()
    await _seed_many(engine, resistors, 200)

    plan = await _explain(
        engine,
        'SELECT id FROM part_definitions WHERE attributes @> \'{"mounting": "smd"}\'',
    )

    assert "ix_part_definitions_attributes" in plan, plan


# --- Facets: counts add up, and no values means no range -------------------------------


def _definition(
    category: Category, key: AttributeKey, kind: AttributeKind, *, options: tuple[str, ...] = ()
) -> AttributeDefinition:
    """One attribute definition for a facet test — only its key, kind and options matter here."""
    return AttributeDefinition(
        AttributeDefinitionId(uuid7()),
        BENCH,
        category.id,
        key,
        AttributeLabel(str(key).capitalize()),
        kind,
        OHM if kind is AttributeKind.NUMBER else None,
        options=options,
    )


async def _facets(engine: AsyncEngine, spec: Spec, schema: AttributeSchema) -> Facets:
    async with catalog(engine) as work:
        return await work.parts.facets(spec, schema)


async def test_facets_count_options_booleans_and_number_ranges(engine: AsyncEngine) -> None:
    # Requirement 5.1: each enum option's count, each boolean's true/false, each number's
    # lowest and highest value, over the parts the spec matches.
    resistors = a_category()
    parts = [
        a_part(
            resistors,
            "smd 220R yes",
            attributes={MOUNTING: "smd", ROHS: True, RESISTANCE: SiValue(Decimal("220"))},
        ),
        a_part(
            resistors,
            "smd 4k7 no",
            attributes={MOUNTING: "smd", ROHS: False, RESISTANCE: SiValue(Decimal("4700"))},
        ),
        a_part(
            resistors,
            "axial 100k yes",
            attributes={MOUNTING: "axial", ROHS: True, RESISTANCE: SiValue(Decimal("100000"))},
        ),
        # A wrong-kind mounting (a number) and no resistance: it counts toward neither.
        a_part(resistors, "wrong kind", attributes={MOUNTING: SiValue(Decimal("1"))}),
    ]
    await save(engine, resistors, parts)
    schema = AttributeSchema(
        [
            _definition(
                resistors, MOUNTING, AttributeKind.ENUM, options=("smd", "axial", "through-hole")
            ),
            _definition(resistors, ROHS, AttributeKind.BOOL),
            _definition(resistors, RESISTANCE, AttributeKind.NUMBER),
        ]
    )

    facets = await _facets(engine, InCategories(frozenset({resistors.id})), schema)

    # Each option counted, an option nobody holds is zero, the wrong-kind value left out.
    assert facets.enums[MOUNTING] == {"smd": 2, "axial": 1, "through-hole": 0}
    # The counts sum to the parts holding one of the options (three), not the four parts.
    assert sum(facets.enums[MOUNTING].values()) == 3
    assert facets.bools[ROHS] == BoolCounts(true=2, false=1)
    # The range's ends are values some part holds (requirement 5.2, property 5).
    assert facets.numbers[RESISTANCE] == NumberRange(
        SiValue(Decimal("220")), SiValue(Decimal("100000"))
    )


async def test_a_number_attribute_with_no_values_has_no_range(engine: AsyncEngine) -> None:
    # Requirement 5.3: a number attribute no matching part holds a value for answers no range.
    resistors = a_category()
    parts = [
        a_part(resistors, "text value", attributes={RESISTANCE: "not a number"}),
        a_part(resistors, "no value"),
    ]
    await save(engine, resistors, parts)
    schema = AttributeSchema([_definition(resistors, RESISTANCE, AttributeKind.NUMBER)])

    facets = await _facets(engine, InCategories(frozenset({resistors.id})), schema)

    # No numeric value among the matching parts, so the range is None rather than a failure.
    assert facets.numbers[RESISTANCE] is None


async def test_facets_count_only_the_parts_the_spec_matches(engine: AsyncEngine) -> None:
    # Requirement 5.2: a text narrowing counts only the parts it matches; the rest don't
    # inflate the counts, so a facet is over the same set a search of that text would be.
    resistors = a_category()
    matching = a_part(resistors, "SDA smd", attributes={MOUNTING: "smd"})
    other = a_part(resistors, "power axial", attributes={MOUNTING: "axial"})
    await save(engine, resistors, [matching, other])
    schema = AttributeSchema(
        [_definition(resistors, MOUNTING, AttributeKind.ENUM, options=("smd", "axial"))]
    )
    spec = AllOf((InCategories(frozenset({resistors.id})), TextContains(SearchText("sda"))))

    facets = await _facets(engine, spec, schema)

    # Only the SDA part is counted; the axial one the text doesn't match stays out.
    assert facets.enums[MOUNTING] == {"smd": 1, "axial": 0}


# --- Property 1: the database and the domain agree -------------------------------------
#
# For a generated set of parts (values of every kind, some missing, some wrong-kind) and a
# generated valid search, the ids the repository returns across every page equal the ids the
# domain's `matches` selects, in the same order (requirement 7.4).

_MOUNTINGS = ("smd", "through-hole", "axial")


@dataclass(frozen=True)
class _PartPlan:
    """The plain description of one part to seed: attribute values, a name, whether it has a pin.

    Plain data only, no ids: `uuid7()` is a side effect, and a strategy that called it would
    generate different ids on replay and Hypothesis would flag it flaky. The test turns each
    plan into a real `PartDefinition` (its own id and pinout) after generation.
    """

    resistance: int | None
    mounting: str | int | None  # a string option, or 7 for a wrong-kind number, or none
    rohs: bool | None
    name: str
    has_sda_pin: bool

    def attributes(self) -> dict[AttributeKey, object]:
        values: dict[AttributeKey, object] = {}
        if self.resistance is not None:
            values[RESISTANCE] = SiValue(Decimal(self.resistance))
        if self.mounting is not None:
            values[MOUNTING] = (
                SiValue(Decimal(self.mounting)) if isinstance(self.mounting, int) else self.mounting
            )
        if self.rohs is not None:
            values[ROHS] = self.rohs
        return values

    def pinout(self) -> Pinout:
        if not self.has_sda_pin:
            return Pinout.empty()
        return Pinout.parse([RawPin(number="1", label="SDA", type="io")])


_PART_PLANS = st.builds(
    _PartPlan,
    resistance=st.none() | st.integers(min_value=1, max_value=1_000_000),
    mounting=st.none() | st.sampled_from([*_MOUNTINGS, 7]),  # 7 is a wrong-kind number
    rohs=st.none() | st.booleans(),
    name=st.sampled_from(["R 4k7", "SDA shifter", "Capacitor", "LED"]),
    has_sda_pin=st.booleans(),
)


@st.composite
def _filters(draw: st.DrawFn) -> tuple[Spec, ...]:
    """A subset of the filter kinds over the seeded keys, minus the category (the test adds it).

    Draws no ids, so it is a plain `@given` strategy: whatever it draws is the same on replay.
    """
    specs: list[Spec] = []
    if draw(st.booleans()):
        specs.append(TextContains(SearchText(draw(st.sampled_from(["r", "sda", "cap"])))))
    if draw(st.booleans()):
        low, high = sorted(draw(st.tuples(_ohms(), _ohms())))
        specs.append(NumberBetween(RESISTANCE, SiValue(Decimal(low)), SiValue(Decimal(high))))
    if draw(st.booleans()):
        picks = draw(st.lists(st.sampled_from(_MOUNTINGS), min_size=1, max_size=3, unique=True))
        specs.append(OneOf(MOUNTING, frozenset(picks)))
    if draw(st.booleans()):
        specs.append(IsBool(ROHS, value=draw(st.booleans())))
    if draw(st.booleans()):
        specs.append(HasPin(SearchText("sda")))
    return tuple(specs)


def _ohms() -> st.SearchStrategy[int]:
    return st.integers(min_value=1, max_value=1_000_000)


_SORTS = st.sampled_from(
    [
        PartSort.newest(SortDirection.DESC),
        PartSort.newest(SortDirection.ASC),
        PartSort.by_name(SortDirection.ASC),
        PartSort.by_name(SortDirection.DESC),
        PartSort.by_attribute(RESISTANCE, SortDirection.ASC),
        PartSort.by_attribute(RESISTANCE, SortDirection.DESC),
    ]
)


def _domain_ids(
    parts: list[tuple[PartDefinition, Pinout]], spec: Spec, sort: PartSort
) -> list[PartDefinitionId]:
    """The ids the domain selects, ordered exactly as the SQL orders them.

    The comparator is the fake's `_ordering` (tests/support/catalog.py): value in the
    direction, nulls last, id ascending. Reusing it, rather than a second copy, is what keeps
    the oracle Property 1 checks the database against identical to the one the fake pages by.
    """
    matching = [part for part, pinout in parts if spec.matches(part, pinout)]
    matching.sort(key=cmp_to_key(_ordering(sort)))
    return [part.id for part in matching]


@settings(max_examples=25, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(plans=st.lists(_PART_PLANS, max_size=8), filters=_filters(), sort=_SORTS)
async def test_the_database_and_the_domain_agree(
    engine: AsyncEngine, plans: list[_PartPlan], filters: tuple[Spec, ...], sort: PartSort
) -> None:
    """Validates: Requirements 1.1, 1.2, 2.1, 2.3, 2.4, 2.5, 2.6, 2.7, 3.1, 4.1, 4.2, 7.4"""
    await _truncate(engine)
    resistors = a_category()
    # The ids are minted here, not in a strategy, so generation stays deterministic on replay.
    parts = [
        (a_part(resistors, plan.name, attributes=plan.attributes()), plan.pinout())
        for plan in plans
    ]
    spec = AllOf((InCategories(frozenset({resistors.id})), *filters))
    await save(
        engine,
        resistors,
        [part for part, _ in parts],
        pinouts={part.id: pinout for part, pinout in parts if len(pinout)},
    )

    from_db = await ids_of(engine, spec, sort)

    assert from_db == _domain_ids(parts, spec, sort)


# --- Property 2: paging neither repeats nor skips --------------------------------------


async def _all_pages(
    engine: AsyncEngine, spec: Spec, sort: PartSort, page_size: int
) -> list[PartDefinitionId]:
    """Every id a search yields, followed page by page to the end through its cursors."""
    ids: list[PartDefinitionId] = []
    cursor: SearchCursor | None = None
    async with catalog(engine) as work:
        while True:
            page: Page[PartDefinition, SearchCursor] = await work.parts.search(
                spec, sort, cursor, page_size
            )
            ids.extend(part.id for part in page.items)
            if page.next_cursor is None:
                return ids
            cursor = page.next_cursor


@settings(max_examples=20, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    count=st.integers(min_value=0, max_value=15),
    shared=st.sampled_from([100, 4700]),
    page_size=st.integers(min_value=1, max_value=100),
    sort=_SORTS,
)
async def test_paging_neither_repeats_nor_skips(
    engine: AsyncEngine, count: int, shared: int, page_size: int, sort: PartSort
) -> None:
    """Validates: Requirements 4.3, 4.5"""
    await _truncate(engine)
    resistors = a_category()
    # Ties on the sort value are the hard case, so many parts share a resistance on purpose.
    parts = [
        a_part(resistors, f"P{n}", attributes={RESISTANCE: SiValue(Decimal(shared))})
        for n in range(count)
    ]
    await save(engine, resistors, parts)
    spec = InCategories(frozenset({resistors.id}))

    paged = await _all_pages(engine, spec, sort, page_size)
    whole = await ids_of(engine, spec, sort)

    # No repeats, nothing skipped, and the same order the one-shot page produced.
    assert paged == whole
    assert len(paged) == count
