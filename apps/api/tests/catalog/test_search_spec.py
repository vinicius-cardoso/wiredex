"""Every filter's `matches`: what it selects, what it leaves out, and that wrong-kind or
missing values never match. The Specification the fakes and the SQL compiler must agree on.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid7

import pytest
from hypothesis import given
from hypothesis import strategies as st

from wiredex.catalog.domain.category import Category
from wiredex.catalog.domain.errors import InvalidFilterError
from wiredex.catalog.domain.part import PartDefinition, PartDetails
from wiredex.catalog.domain.pinout import Pin, PinFunction, PinLabel, PinNumber, Pinout, PinType
from wiredex.catalog.domain.schema import AttributeValues
from wiredex.catalog.domain.search import (
    MAX_SEARCH_TEXT_LENGTH,
    AllOf,
    HasPin,
    InCategories,
    IsBool,
    NumberBetween,
    OneOf,
    SearchText,
    Spec,
    TextAttributeContains,
    TextContains,
)
from wiredex.catalog.domain.values import (
    AttributeKey,
    CategoryId,
    CategoryName,
    Manufacturer,
    Mpn,
    Package,
    PartDefinitionId,
    PartName,
    SiValue,
    WorkspaceId,
)

NOW = datetime(2026, 9, 25, 10, 0, tzinfo=UTC)
BENCH = WorkspaceId(uuid7())
RESISTANCE = AttributeKey("resistance")
LEAD_FREE = AttributeKey("lead_free")
NOTE = AttributeKey("note")
RESISTORS = CategoryId(uuid7())


FULL_DETAILS = PartDetails(
    PartName("Resistor 4.7k"), Manufacturer("Yageo"), Mpn("RC0805FR-074K7L"), Package("0805")
)


def part(
    *,
    category_id: CategoryId = RESISTORS,
    details: PartDetails = FULL_DETAILS,
    attributes: dict[AttributeKey, object] | None = None,
) -> PartDefinition:
    category = Category(category_id, BENCH, None, CategoryName("Resistors"), NOW)
    return PartDefinition.define(
        PartDefinitionId(uuid7()), category, details, AttributeValues(attributes or {}), NOW
    )


def with_pins(*labelled: tuple[str, ...]) -> Pinout:
    # A unique number per row, since a pinout refuses two pins that share one; the number
    # itself doesn't matter to a pin filter, which reads only labels and functions.
    return Pinout(
        Pin(
            PinNumber(str(row)),
            PinLabel(entry[0]),
            PinType.IO,
            tuple(PinFunction(function) for function in entry[1:]),
        )
        for row, entry in enumerate(labelled, start=1)
    )


NO_PINS = Pinout.empty()


def ohms(value: str) -> SiValue:
    return SiValue(Decimal(value))


# --- SearchText ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [("  SDA  ", "SDA"), ("4k7", "4k7"), ("a\t\n  b", "a b")],
)
def test_search_text_is_trimmed_and_its_whitespace_collapsed(text: str, expected: str) -> None:
    assert str(SearchText(text)) == expected


@pytest.mark.parametrize("text", ["", "   ", "x" * (MAX_SEARCH_TEXT_LENGTH + 1)])
def test_search_text_refuses_empty_or_over_long(text: str) -> None:
    with pytest.raises(InvalidFilterError):
        SearchText(text)


# --- TextContains ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "fragment",
    ["resistor", "RESISTOR", "yageo", "074K7", "0805"],
)
def test_text_contains_matches_any_identifying_field_ignoring_case(fragment: str) -> None:
    assert TextContains(SearchText(fragment)).matches(part(), NO_PINS)


def test_text_contains_does_not_match_when_no_field_holds_the_fragment() -> None:
    assert not TextContains(SearchText("capacitor")).matches(part(), NO_PINS)


def test_text_contains_ignores_fields_that_are_absent() -> None:
    bare = part(details=PartDetails(PartName("Resistor 4.7k")))

    assert TextContains(SearchText("resistor")).matches(bare, NO_PINS)
    assert not TextContains(SearchText("yageo")).matches(bare, NO_PINS)


# --- InCategories ----------------------------------------------------------------------


def test_in_categories_matches_a_part_of_a_listed_category() -> None:
    other = CategoryId(uuid7())
    spec = InCategories(frozenset({RESISTORS, other}))

    assert spec.matches(part(category_id=RESISTORS), NO_PINS)
    assert spec.matches(part(category_id=other), NO_PINS)


def test_in_categories_does_not_match_a_part_of_another_category() -> None:
    spec = InCategories(frozenset({RESISTORS}))

    assert not spec.matches(part(category_id=CategoryId(uuid7())), NO_PINS)


# --- NumberBetween ---------------------------------------------------------------------


def test_number_between_matches_a_value_within_the_bounds_inclusive() -> None:
    spec = NumberBetween(RESISTANCE, ohms("1000"), ohms("10000"))

    assert spec.matches(part(attributes={RESISTANCE: ohms("1000")}), NO_PINS)  # lower edge
    assert spec.matches(part(attributes={RESISTANCE: ohms("4700")}), NO_PINS)
    assert spec.matches(part(attributes={RESISTANCE: ohms("10000")}), NO_PINS)  # upper edge


def test_number_between_leaves_out_a_value_outside_the_bounds() -> None:
    spec = NumberBetween(RESISTANCE, ohms("1000"), ohms("10000"))

    assert not spec.matches(part(attributes={RESISTANCE: ohms("220")}), NO_PINS)
    assert not spec.matches(part(attributes={RESISTANCE: ohms("22000")}), NO_PINS)


def test_number_between_with_one_bound_is_open_on_the_other_side() -> None:
    at_least = NumberBetween(RESISTANCE, ohms("1000"), None)
    at_most = NumberBetween(RESISTANCE, None, ohms("1000"))

    assert at_least.matches(part(attributes={RESISTANCE: ohms("50000")}), NO_PINS)
    assert not at_least.matches(part(attributes={RESISTANCE: ohms("500")}), NO_PINS)
    assert at_most.matches(part(attributes={RESISTANCE: ohms("500")}), NO_PINS)
    assert not at_most.matches(part(attributes={RESISTANCE: ohms("50000")}), NO_PINS)


def test_number_between_leaves_out_a_missing_value() -> None:
    spec = NumberBetween(RESISTANCE, ohms("1000"), ohms("10000"))

    assert not spec.matches(part(attributes={}), NO_PINS)


def test_number_between_leaves_out_a_wrong_kind_value() -> None:
    # After a schema change a resistance may hold text where a number is expected.
    spec = NumberBetween(RESISTANCE, ohms("1000"), ohms("10000"))

    assert not spec.matches(part(attributes={RESISTANCE: "5k"}), NO_PINS)
    assert not spec.matches(part(attributes={RESISTANCE: True}), NO_PINS)


def test_number_between_needs_at_least_one_bound() -> None:
    with pytest.raises(InvalidFilterError):
        NumberBetween(RESISTANCE, None, None)


def test_number_between_refuses_a_minimum_above_its_maximum() -> None:
    with pytest.raises(InvalidFilterError):
        NumberBetween(RESISTANCE, ohms("10000"), ohms("1000"))


# --- OneOf -----------------------------------------------------------------------------


def test_one_of_matches_a_value_among_the_options() -> None:
    package = AttributeKey("package_size")
    spec = OneOf(package, frozenset({"0805", "0603"}))

    assert spec.matches(part(attributes={package: "0805"}), NO_PINS)
    assert not spec.matches(part(attributes={package: "1206"}), NO_PINS)


def test_one_of_leaves_out_a_missing_or_wrong_kind_value() -> None:
    key = AttributeKey("package_size")
    spec = OneOf(key, frozenset({"0805"}))

    assert not spec.matches(part(attributes={}), NO_PINS)
    assert not spec.matches(part(attributes={key: ohms("805")}), NO_PINS)


def test_one_of_needs_at_least_one_option() -> None:
    with pytest.raises(InvalidFilterError):
        OneOf(AttributeKey("package_size"), frozenset())


# --- IsBool ----------------------------------------------------------------------------


@pytest.mark.parametrize("wanted", [True, False])
def test_is_bool_matches_the_value_asked_for(wanted: bool) -> None:
    spec = IsBool(LEAD_FREE, wanted)

    assert spec.matches(part(attributes={LEAD_FREE: wanted}), NO_PINS)
    assert not spec.matches(part(attributes={LEAD_FREE: not wanted}), NO_PINS)


def test_is_bool_leaves_out_a_missing_value() -> None:
    assert not IsBool(LEAD_FREE, True).matches(part(attributes={}), NO_PINS)


def test_is_bool_leaves_out_a_wrong_kind_value() -> None:
    # A stored 1 or "true" must not match through truthiness: only a real bool does.
    assert not IsBool(LEAD_FREE, True).matches(part(attributes={LEAD_FREE: "true"}), NO_PINS)
    assert not IsBool(LEAD_FREE, True).matches(part(attributes={LEAD_FREE: ohms("1")}), NO_PINS)


# --- TextAttributeContains -------------------------------------------------------------


def test_text_attribute_contains_matches_a_fragment_ignoring_case() -> None:
    spec = TextAttributeContains(NOTE, SearchText("thin"))

    assert spec.matches(part(attributes={NOTE: "Thin film, low noise"}), NO_PINS)
    assert not spec.matches(part(attributes={NOTE: "Thick film"}), NO_PINS)


def test_text_attribute_contains_leaves_out_a_missing_or_wrong_kind_value() -> None:
    spec = TextAttributeContains(NOTE, SearchText("thin"))

    assert not spec.matches(part(attributes={}), NO_PINS)
    assert not spec.matches(part(attributes={NOTE: ohms("1")}), NO_PINS)


# --- HasPin ----------------------------------------------------------------------------


def test_has_pin_matches_a_label_ignoring_case() -> None:
    pins = with_pins(("SDA",), ("SCL",))

    assert HasPin(SearchText("sda")).matches(part(), pins)


def test_has_pin_matches_an_alternate_function_ignoring_case() -> None:
    pins = with_pins(("GPIO21", "I2C0_SDA", "SDA"))

    assert HasPin(SearchText("sda")).matches(part(), pins)


def test_has_pin_does_not_match_when_no_pin_carries_the_name() -> None:
    pins = with_pins(("GPIO21", "TOUCH9"))

    assert not HasPin(SearchText("SDA")).matches(part(), pins)


def test_has_pin_does_not_match_a_part_with_no_pins() -> None:
    assert not HasPin(SearchText("SDA")).matches(part(), NO_PINS)


# --- AllOf -----------------------------------------------------------------------------


def test_all_of_matches_only_when_every_filter_holds() -> None:
    spec = AllOf(
        (
            InCategories(frozenset({RESISTORS})),
            NumberBetween(RESISTANCE, ohms("1000"), ohms("10000")),
        )
    )

    assert spec.matches(part(attributes={RESISTANCE: ohms("4700")}), NO_PINS)
    assert not spec.matches(part(attributes={RESISTANCE: ohms("220")}), NO_PINS)
    assert not spec.matches(
        part(category_id=CategoryId(uuid7()), attributes={RESISTANCE: ohms("4700")}), NO_PINS
    )


def test_an_empty_all_of_matches_every_part() -> None:
    empty = AllOf(())

    assert empty.matches(part(), NO_PINS)
    assert empty.matches(part(details=PartDetails(PartName("Bare")), attributes={}), NO_PINS)


# --- Property: a filter never raises, whatever kind the stored value is -----------------

_STORED_VALUES = st.one_of(
    st.builds(lambda n: ohms(str(n)), st.integers(min_value=-10_000, max_value=10_000)),
    st.text(max_size=20),
    st.booleans(),
)


@given(stored=st.none() | _STORED_VALUES)
def test_matches_answers_a_bool_for_any_stored_kind_and_never_raises(stored: object) -> None:
    # Requirement 2.7: a value of the wrong kind is left out, never a failure.
    attributes = {} if stored is None else {RESISTANCE: stored}
    specs: tuple[Spec, ...] = (
        NumberBetween(RESISTANCE, ohms("1000"), ohms("10000")),
        OneOf(RESISTANCE, frozenset({"0805"})),
        IsBool(RESISTANCE, True),
        TextAttributeContains(RESISTANCE, SearchText("film")),
    )
    for spec in specs:
        assert isinstance(spec.matches(part(attributes=attributes), NO_PINS), bool)
