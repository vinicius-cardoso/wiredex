from collections.abc import Callable

import pytest

from wiredex.catalog.domain.errors import (
    CatalogError,
    InvalidAttributeKeyError,
    InvalidLabelError,
    InvalidNameError,
    InvalidPartDetailError,
)
from wiredex.catalog.domain.values import (
    AttributeKey,
    AttributeKind,
    AttributeLabel,
    CategoryName,
    Manufacturer,
    Mpn,
    Package,
    PartName,
)

# The six values that share the trim, collapse and cap rule, with the cap the design gives them.
TEXT_VALUES: list[tuple[Callable[[str], object], int]] = [
    (CategoryName, 80),
    (PartName, 120),
    (AttributeLabel, 80),
    (Manufacturer, 80),
    (Mpn, 80),
    (Package, 40),
]


@pytest.mark.parametrize("value", [factory for factory, _ in TEXT_VALUES])
def test_text_values_are_trimmed_and_have_their_whitespace_collapsed(
    value: Callable[[str], object],
) -> None:
    assert str(value("  Thick   film  ")) == "Thick film"


@pytest.mark.parametrize(("value", "cap"), TEXT_VALUES)
def test_text_values_accept_their_cap_and_refuse_one_character_more(
    value: Callable[[str], object], cap: int
) -> None:
    assert str(value("x" * cap)) == "x" * cap
    with pytest.raises(CatalogError, match=f"between 1 and {cap} characters"):
        value("x" * (cap + 1))


@pytest.mark.parametrize("value", [factory for factory, _ in TEXT_VALUES])
@pytest.mark.parametrize("text", ["", "   ", "\t\n"])
def test_blank_text_is_never_a_value(value: Callable[[str], object], text: str) -> None:
    with pytest.raises(CatalogError):
        value(text)


@pytest.mark.parametrize(
    ("value", "error"),
    [
        (CategoryName, InvalidNameError),
        (PartName, InvalidNameError),
        (AttributeLabel, InvalidLabelError),
        (AttributeKey, InvalidAttributeKeyError),
        (Manufacturer, InvalidPartDetailError),
        (Mpn, InvalidPartDetailError),
        (Package, InvalidPartDetailError),
    ],
)
def test_each_value_refuses_with_its_own_error(
    value: Callable[[str], object], error: type[CatalogError]
) -> None:
    with pytest.raises(error):
        value("")


def test_names_and_labels_keep_the_case_they_were_typed_in() -> None:
    # Case is the owner's choice; only keys and MPN comparisons ignore it.
    assert CategoryName("Thick Film").value == "Thick Film"
    assert PartName("BME280 Sensor").value == "BME280 Sensor"
    assert AttributeLabel("Resistance (Ω)").value == "Resistance (Ω)"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("resistance", "resistance"),
        ("  Resistance  ", "resistance"),
        ("TOLERANCE_PCT", "tolerance_pct"),
        ("v_max_2", "v_max_2"),
        ("a", "a"),
        ("a" * 40, "a" * 40),
    ],
)
def test_attribute_keys_are_trimmed_and_lower_cased(text: str, expected: str) -> None:
    assert AttributeKey(text).value == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "1st_choice",  # has to start with a letter
        "_leading",
        "with space",
        "with-dash",
        "with.dot",
        "resistância",  # ASCII only: it is a JSONB key and a query identifier
        "a" * 41,
    ],
)
def test_keys_that_are_not_lower_case_slugs_are_refused(text: str) -> None:
    with pytest.raises(InvalidAttributeKeyError, match="is not a key like resistance"):
        AttributeKey(text)


def test_mpns_compare_case_insensitively_for_uniqueness_but_keep_their_case() -> None:
    printed = Mpn("BME280")

    assert printed.value == "BME280"
    assert printed.fold() == Mpn("bme280").fold()
    # Folding is for the uniqueness check; the values themselves stay distinct.
    assert printed != Mpn("bme280")


def test_the_attribute_kinds_are_exactly_adr_0005s_four() -> None:
    assert [kind.value for kind in AttributeKind] == ["number", "enum", "text", "bool"]
    assert AttributeKind("number") is AttributeKind.NUMBER
    # A StrEnum, so the kind reaches JSON and the CHECK constraint as its own name.
    assert str(AttributeKind.BOOL) == "bool"
