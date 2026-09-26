"""Search and facets over the in-memory catalog, against the chosen category's schema.

`SearchParts` turns raw filters into typed ones against the resolved schema, refusing what
doesn't fit (requirements 2.8, 2.9); it reads range bounds with the attribute's unit
(requirement 2.2); it includes a category's descendants unless asked for it alone
(requirement 1.2); it orders and pages a result (requirements 4.1, 4.5). `CategoryFacets`
counts over category, text and pin only (requirements 5.1, 5.2, 5.3). Properties 4 and 5 are
the last two tests.

The bench is *Passives → Resistors* with a required `resistance` in ohms; each test adds the
attributes and parts it needs.
"""

from collections.abc import Mapping
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from support.catalog import BENCH, OHM, World
from wiredex.catalog.application.attributes import NewAttribute
from wiredex.catalog.application.categories import NewCategory
from wiredex.catalog.application.parts import NewPart
from wiredex.catalog.application.search import PartSearch, RawFilter
from wiredex.catalog.domain.category import Category
from wiredex.catalog.domain.errors import (
    CategoryNotFoundError,
    InvalidCursorError,
    InvalidFilterError,
    InvalidSortError,
)
from wiredex.catalog.domain.part import PartDefinition, PartDetails
from wiredex.catalog.domain.values import (
    AttributeKey,
    AttributeKind,
    AttributeLabel,
    CategoryName,
    PartName,
)

pytestmark = pytest.mark.anyio

RESISTANCE = AttributeKey("resistance")


def details(name: str) -> PartDetails:
    return PartDetails(PartName(name))


async def a_resistor(
    world: World,
    name: str = "R 4k7 0805",
    resistance: str | None = "4k7",
    category: Category | None = None,
) -> PartDefinition:
    typed: Mapping[str, object] = {} if resistance is None else {"resistance": resistance}
    where = world.resistors if category is None else category
    return await world.define_part(BENCH, NewPart(where.id, details(name), typed))


async def a_choice_attribute(
    world: World, key: str, options: tuple[str, ...], *, category: Category | None = None
) -> None:
    await world.define_attribute(
        BENCH,
        (category or world.resistors).id,
        NewAttribute(AttributeKey(key), AttributeLabel(key), AttributeKind.ENUM, options=options),
    )


async def a_bool_attribute(world: World, key: str) -> None:
    await world.define_attribute(
        BENCH,
        world.resistors.id,
        NewAttribute(AttributeKey(key), AttributeLabel(key), AttributeKind.BOOL),
    )


async def names(world: World, search: PartSearch) -> list[str]:
    page = await world.search_parts(BENCH, search)
    return [str(part.name) for part in page.items]


# --- Text and category (requirements 1.2, 1.3, 1.4) ------------------------------------


async def test_nothing_given_returns_every_part_of_the_workspace() -> None:
    world = World()
    capacitors = world.add_category("Capacitors")
    await a_resistor(world, "R 4k7 0805")
    world.add_part(capacitors, "C 100n 0603")

    assert sorted(await names(world, PartSearch())) == ["C 100n 0603", "R 4k7 0805"]


async def test_a_category_includes_its_descendants() -> None:
    # Requirement 1.2: a search of Passives finds the resistors under it.
    world = World()
    thick_film = await world.create_category(
        BENCH, NewCategory(CategoryName("Thick film"), world.resistors.id)
    )
    await a_resistor(world, "R in resistors")
    await a_resistor(world, "R in thick film", category=thick_film)

    found = await names(world, PartSearch(category_id=world.passives.id))

    assert sorted(found) == ["R in resistors", "R in thick film"]


async def test_exact_category_excludes_the_descendants() -> None:
    # Requirement 1.2's "unless asked for that category alone".
    world = World()
    thick_film = await world.create_category(
        BENCH, NewCategory(CategoryName("Thick film"), world.resistors.id)
    )
    await a_resistor(world, "R in resistors")
    await a_resistor(world, "R in thick film", category=thick_film)

    found = await names(world, PartSearch(category_id=world.resistors.id, exact_category=True))

    assert found == ["R in resistors"]


async def test_text_and_category_both_narrow() -> None:
    # Requirement 1.3: only parts matching both come back.
    world = World()
    capacitors = world.add_category("Capacitors")
    await a_resistor(world, "R 4k7 0805")
    await a_resistor(world, "R 10k 0805")
    world.add_part(capacitors, "R-shaped capacitor")

    found = await names(world, PartSearch(text="4k7", category_id=world.resistors.id))

    assert found == ["R 4k7 0805"]


async def test_an_unknown_category_is_not_found() -> None:
    world = World()
    ghost = world.add_category("Ghost")
    world.catalog.categories.saved.pop(ghost.id)

    with pytest.raises(CategoryNotFoundError):
        await world.search_parts(BENCH, PartSearch(category_id=ghost.id))


# --- Filter refusals (requirements 2.8, 2.9) -------------------------------------------


async def test_an_attribute_filter_without_a_category_is_refused() -> None:
    # Requirement 2.8: only a category's schema says what a key means.
    world = World()

    with pytest.raises(InvalidFilterError, match="needs a category"):
        await world.search_parts(
            BENCH, PartSearch(filters=[RawFilter(key="resistance", minimum="1k")])
        )


async def test_a_filter_on_an_unknown_key_is_refused_naming_it() -> None:
    # Requirement 2.9: the resolved schema doesn't define this key.
    world = World()

    with pytest.raises(InvalidFilterError, match="resistence"):
        await world.search_parts(
            BENCH,
            PartSearch(
                category_id=world.resistors.id,
                filters=[RawFilter(key="resistence", minimum="1k")],
            ),
        )


async def test_a_range_on_an_enum_attribute_is_refused() -> None:
    # Requirement 2.9: a range doesn't fit an enum's kind.
    world = World()
    await a_choice_attribute(world, "mounting", ("smd", "through-hole"))

    with pytest.raises(InvalidFilterError, match="mounting"):
        await world.search_parts(
            BENCH,
            PartSearch(
                category_id=world.resistors.id,
                filters=[RawFilter(key="mounting", minimum="1")],
            ),
        )


async def test_a_range_with_its_minimum_above_its_maximum_is_refused() -> None:
    # Requirement 2.9: the domain filter refuses it, the message names the filter.
    world = World()

    with pytest.raises(InvalidFilterError, match="resistance"):
        await world.search_parts(
            BENCH,
            PartSearch(
                category_id=world.resistors.id,
                filters=[RawFilter(key="resistance", minimum="10k", maximum="1k")],
            ),
        )


async def test_an_unreadable_range_bound_is_refused_naming_the_filter() -> None:
    # Requirement 2.9's "unreadable bound": K is kelvin, not the kilo the owner meant.
    world = World()

    with pytest.raises(InvalidFilterError, match="resistance"):
        await world.search_parts(
            BENCH,
            PartSearch(
                category_id=world.resistors.id,
                filters=[RawFilter(key="resistance", minimum="4K7")],
            ),
        )


# --- Filters read the schema (requirements 2.2, 2.6) -----------------------------------


async def test_a_number_range_bound_is_read_with_the_attributes_unit() -> None:
    # Requirement 2.2: 1k..10k means 1000..10000 ohms, so 4k7 is in and 220R is out.
    world = World()
    await a_resistor(world, "R 220R", "220R")
    await a_resistor(world, "R 4k7", "4k7")
    await a_resistor(world, "R 47k", "47k")

    found = await names(
        world,
        PartSearch(
            category_id=world.resistors.id,
            filters=[RawFilter(key="resistance", minimum="1k", maximum="10k")],
        ),
    )

    assert found == ["R 4k7"]


async def test_several_filters_all_have_to_hold() -> None:
    # Requirement 2.6: a resistor in range and smd, not a smd one out of range.
    world = World()
    await a_choice_attribute(world, "mounting", ("smd", "through-hole"))
    await world.define_part(
        BENCH,
        NewPart(
            world.resistors.id, details("in range smd"), {"resistance": "4k7", "mounting": "smd"}
        ),
    )
    await world.define_part(
        BENCH,
        NewPart(
            world.resistors.id,
            details("out of range smd"),
            {"resistance": "47k", "mounting": "smd"},
        ),
    )

    found = await names(
        world,
        PartSearch(
            category_id=world.resistors.id,
            filters=[
                RawFilter(key="resistance", minimum="1k", maximum="10k"),
                RawFilter(key="mounting", options=["smd"]),
            ],
        ),
    )

    assert found == ["in range smd"]


# --- Sorting (requirement 4.1) ---------------------------------------------------------


async def test_the_default_sort_is_newest_first() -> None:
    world = World()
    first = await a_resistor(world, "R first")
    second = await a_resistor(world, "R second")

    found = await names(world, PartSearch(category_id=world.resistors.id))

    # UUIDv7 ids grow with time, so the later part comes first under newest-descending.
    assert found == ["R second", "R first"]
    assert first.id < second.id


async def test_a_search_sorts_by_name() -> None:
    world = World()
    await a_resistor(world, "Bravo")
    await a_resistor(world, "Alpha")
    await a_resistor(world, "Charlie")

    ascending = await names(
        world, PartSearch(category_id=world.resistors.id, sort="name", direction="asc")
    )
    descending = await names(
        world, PartSearch(category_id=world.resistors.id, sort="name", direction="desc")
    )

    assert ascending == ["Alpha", "Bravo", "Charlie"]
    assert descending == ["Charlie", "Bravo", "Alpha"]


async def test_a_search_sorts_by_a_number_attribute() -> None:
    # Requirement 4.1: the smallest resistor first when ascending.
    world = World()
    await a_resistor(world, "R 220R", "220R")
    await a_resistor(world, "R 47k", "47k")
    await a_resistor(world, "R 4k7", "4k7")

    found = await names(
        world,
        PartSearch(category_id=world.resistors.id, sort="attribute:resistance", direction="asc"),
    )

    assert found == ["R 220R", "R 4k7", "R 47k"]


async def a_number_attribute(world: World, key: str) -> None:
    """An optional number attribute, so a part is allowed to have no value for it."""
    await world.define_attribute(
        BENCH,
        world.resistors.id,
        NewAttribute(AttributeKey(key), AttributeLabel(key), AttributeKind.NUMBER, OHM),
    )


async def test_parts_without_the_sort_value_come_last_in_either_direction() -> None:
    # Requirement 4.2: a part missing the number sorts last, ascending and descending.
    world = World()
    await a_number_attribute(world, "power")
    await world.define_part(
        BENCH,
        NewPart(world.resistors.id, details("R has value"), {"resistance": "4k7", "power": "1"}),
    )
    await a_resistor(world, "R no value", "4k7")

    ascending = await names(
        world,
        PartSearch(category_id=world.resistors.id, sort="attribute:power", direction="asc"),
    )
    descending = await names(
        world,
        PartSearch(category_id=world.resistors.id, sort="attribute:power", direction="desc"),
    )

    assert ascending == ["R has value", "R no value"]
    assert descending == ["R has value", "R no value"]


async def test_an_attribute_sort_without_a_category_is_refused() -> None:
    # Requirement 4.1 through InvalidSortError: no schema means no key to read.
    world = World()

    with pytest.raises(InvalidSortError, match="needs a category"):
        await world.search_parts(BENCH, PartSearch(sort="attribute:resistance"))


async def test_an_attribute_sort_on_a_non_number_is_refused() -> None:
    world = World()
    await a_choice_attribute(world, "mounting", ("smd", "through-hole"))

    with pytest.raises(InvalidSortError, match="mounting"):
        await world.search_parts(
            BENCH, PartSearch(category_id=world.resistors.id, sort="attribute:mounting")
        )


async def test_an_unknown_sort_is_refused() -> None:
    world = World()

    with pytest.raises(InvalidSortError):
        await world.search_parts(BENCH, PartSearch(sort="oldest"))


# --- Paging (requirements 4.4, 4.5) ----------------------------------------------------


async def test_a_page_carries_a_cursor_that_continues_the_same_search() -> None:
    # Requirement 4.5: the cursor continues without repeating or skipping a part.
    world = World()
    for index in range(5):
        await a_resistor(world, f"R {index}", f"{index + 1}k")
    search = PartSearch(
        category_id=world.resistors.id, sort="attribute:resistance", direction="asc", limit=2
    )

    first = await world.search_parts(BENCH, search)
    assert [str(part.name) for part in first.items] == ["R 0", "R 1"]
    assert first.next_cursor is not None

    second = await world.search_parts(
        BENCH,
        PartSearch(
            category_id=world.resistors.id,
            sort="attribute:resistance",
            direction="asc",
            limit=2,
            cursor=first.next_cursor.encode(),
        ),
    )
    assert [str(part.name) for part in second.items] == ["R 2", "R 3"]

    third = await world.search_parts(
        BENCH,
        PartSearch(
            category_id=world.resistors.id,
            sort="attribute:resistance",
            direction="asc",
            limit=2,
            cursor=second.next_cursor.encode() if second.next_cursor else None,
        ),
    )
    assert [str(part.name) for part in third.items] == ["R 4"]
    assert third.next_cursor is None


async def test_a_cursor_from_a_different_search_is_refused() -> None:
    # Requirement 4.4: the fingerprint tells a cursor's search from another.
    world = World()
    for index in range(3):
        await a_resistor(world, f"R {index}", f"{index + 1}k")
    first = await world.search_parts(
        BENCH, PartSearch(category_id=world.resistors.id, sort="name", limit=1)
    )
    assert first.next_cursor is not None
    token = first.next_cursor.encode()

    with pytest.raises(InvalidCursorError):
        await world.search_parts(
            BENCH,
            # Same category, a different sort: a different search, so the cursor doesn't fit.
            PartSearch(category_id=world.resistors.id, sort="newest", limit=1, cursor=token),
        )


async def test_the_page_size_has_a_floor_of_one() -> None:
    # Requirement 4.5: a limit below one still returns a page, of one part.
    world = World()
    await a_resistor(world, "R 1k", "1k")
    await a_resistor(world, "R 2k", "2k")

    page = await world.search_parts(BENCH, PartSearch(limit=0))

    assert len(page.items) == 1
    assert page.next_cursor is not None


async def test_a_huge_page_is_capped_at_a_hundred() -> None:
    # Requirement 4.5: over a hundred parts, a page holds a hundred and carries a cursor.
    world = World()
    for index in range(101):
        await a_resistor(world, f"R {index:03d}", f"{index + 1}")

    page = await world.search_parts(BENCH, PartSearch(limit=10_000))

    assert len(page.items) == 100
    assert page.next_cursor is not None


# --- Facets (requirements 5.1, 5.2, 5.3) -----------------------------------------------


async def test_facets_count_each_enum_option_and_boolean_value() -> None:
    world = World()
    await a_choice_attribute(world, "mounting", ("smd", "through-hole"))
    await a_bool_attribute(world, "lead_free")
    await world.define_part(
        BENCH,
        NewPart(
            world.resistors.id,
            details("A"),
            {"resistance": "1k", "mounting": "smd", "lead_free": True},
        ),
    )
    await world.define_part(
        BENCH,
        NewPart(
            world.resistors.id,
            details("B"),
            {"resistance": "2k", "mounting": "smd", "lead_free": False},
        ),
    )
    await world.define_part(
        BENCH,
        NewPart(world.resistors.id, details("C"), {"resistance": "3k", "mounting": "through-hole"}),
    )

    facets = await world.category_facets(BENCH, world.resistors.id)

    assert facets.enums[AttributeKey("mounting")] == {"smd": 2, "through-hole": 1}
    assert facets.bools[AttributeKey("lead_free")].true == 1
    assert facets.bools[AttributeKey("lead_free")].false == 1
    number = facets.numbers[RESISTANCE]
    assert number is not None
    assert (number.minimum.value, number.maximum.value) == (Decimal(1000), Decimal(3000))


async def test_facets_ignore_attribute_filters_but_honour_text() -> None:
    # Requirement 5.2: text narrows the count, an attribute filter never does — there is no
    # place to pass one in, and the range still spans every matching part.
    world = World()
    await a_choice_attribute(world, "mounting", ("smd", "through-hole"))
    await world.define_part(
        BENCH,
        NewPart(world.resistors.id, details("Keep me 1k"), {"resistance": "1k", "mounting": "smd"}),
    )
    await world.define_part(
        BENCH,
        NewPart(world.resistors.id, details("Skip me 9k"), {"resistance": "9k", "mounting": "smd"}),
    )

    facets = await world.category_facets(BENCH, world.resistors.id, text="Keep")

    assert facets.enums[AttributeKey("mounting")] == {"smd": 1, "through-hole": 0}
    number = facets.numbers[RESISTANCE]
    assert number is not None
    assert number.minimum.value == Decimal(1000)
    assert number.maximum.value == Decimal(1000)


async def test_a_number_attribute_with_no_values_has_no_range() -> None:
    # Requirement 5.3: an empty attribute answers None, not a failure.
    world = World()
    await a_number_attribute(world, "power")
    await a_resistor(world, "R with resistance only", "4k7")  # nothing has a power value

    facets = await world.category_facets(BENCH, world.resistors.id)

    assert facets.numbers[AttributeKey("power")] is None
    # The attribute that does have values still gets its range.
    assert facets.numbers[RESISTANCE] is not None


# --- Property 4: a range bound means what a stored value means -------------------------
#
# For any number in engineering notation with the attribute's unit, filtering a part that
# holds that exact value with the text as both minimum and maximum matches the part.

_MAGNITUDES = st.integers(min_value=-6, max_value=6)
_MANTISSAS = st.integers(min_value=1, max_value=9999)


@st.composite
def _si_texts(draw: st.DrawFn) -> str:
    """Engineering notation the catalog reads: a mantissa, a prefix, and the attribute's Ω."""
    mantissa = draw(_MANTISSAS)
    prefix = draw(st.sampled_from(["p", "n", "µ", "m", "", "k", "M", "G"]))
    return f"{mantissa}{prefix}{OHM}"


@given(text=_si_texts())
async def test_a_range_bound_matches_the_value_it_reads(text: str) -> None:
    """Validates: Requirements 2.1, 2.2"""
    world = World()
    part = await a_resistor(world, "R under test", text)

    found = await world.search_parts(
        BENCH,
        PartSearch(
            category_id=world.resistors.id,
            filters=[RawFilter(key="resistance", minimum=text, maximum=text)],
        ),
    )

    assert [item.id for item in found.items] == [part.id]


# --- Property 5: facet counts add up ---------------------------------------------------
#
# For any parts, an enum attribute's option counts sum to the number of parts holding one of
# those options, and a number range's ends are values some part holds.

_OPTIONS = ("smd", "through-hole", "axial")


@given(
    parts=st.lists(
        st.tuples(
            st.sampled_from([*_OPTIONS, None]),  # the enum value, or none
            st.integers(min_value=1, max_value=1_000_000),  # the resistance in ohms
        ),
        min_size=0,
        max_size=12,
    )
)
async def test_facet_counts_add_up(parts: list[tuple[str | None, int]]) -> None:
    """Validates: Requirements 5.1, 5.2"""
    world = World()
    await a_choice_attribute(world, "mounting", _OPTIONS)
    for index, (pick, resistance) in enumerate(parts):
        typed: dict[str, object] = {"resistance": str(resistance)}
        if pick is not None:
            typed["mounting"] = pick
        await world.define_part(BENCH, NewPart(world.resistors.id, details(f"P{index}"), typed))

    facets = await world.category_facets(BENCH, world.resistors.id)

    # Every declared option is present, and the counts sum to the parts that hold one.
    counts = facets.enums[AttributeKey("mounting")]
    assert set(counts) == set(_OPTIONS)
    assert sum(counts.values()) == sum(1 for pick, _ in parts if pick is not None)
    for option in _OPTIONS:
        assert counts[option] == sum(1 for pick, _ in parts if pick == option)

    # A number range's ends are values some part actually holds.
    stored = {Decimal(resistance) for _, resistance in parts}
    number = facets.numbers[RESISTANCE]
    if stored:
        assert number is not None
        assert number.minimum.value == min(stored)
        assert number.maximum.value == max(stored)
    else:
        assert number is None
