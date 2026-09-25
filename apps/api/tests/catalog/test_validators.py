from dataclasses import dataclass
from decimal import Decimal

import pytest

from wiredex.catalog.domain.errors import CatalogError, InvalidNumberError
from wiredex.catalog.domain.validators import (
    MAX_TEXT_LENGTH,
    VALIDATORS,
    AttributeSpec,
    BoolValidator,
    EnumValidator,
    NumberValidator,
    TextValidator,
)
from wiredex.catalog.domain.values import AttributeKey, AttributeKind, SiValue, Unit

OHM = Unit("Ω")
FARAD = Unit("F")


@dataclass(frozen=True, slots=True)
class _Attribute:
    key: AttributeKey
    kind: AttributeKind
    unit: Unit | None = None
    options: tuple[str, ...] = ()


def attribute(
    kind: AttributeKind,
    key: str = "resistance",
    unit: Unit | None = None,
    options: tuple[str, ...] = (),
) -> AttributeSpec:
    """A stand-in for task 5's AttributeDefinition: the return type is what proves any
    definition with these four members is all a validator needs."""
    return _Attribute(AttributeKey(key), kind, unit, options)


NUMBER = attribute(AttributeKind.NUMBER, unit=OHM)
TOLERANCE = attribute(AttributeKind.ENUM, key="tolerance", options=("1%", "5%", "10%"))
NOTES = attribute(AttributeKind.TEXT, key="notes")
ROHS = attribute(AttributeKind.BOOL, key="rohs")
CAPACITANCE = attribute(AttributeKind.NUMBER, key="capacitance", unit=FARAD)


@pytest.mark.parametrize(
    ("definition", "raw", "expected"),
    [
        (NUMBER, "4k7", SiValue(Decimal(4700))),
        (TOLERANCE, "5%", "5%"),
        (NOTES, "  from the parts bin  ", "from the parts bin"),
        (ROHS, True, True),
    ],
)
def test_each_kind_stores_the_value_its_validator_reads(
    definition: AttributeSpec, raw: object, expected: object
) -> None:
    # Through VALIDATORS, the way the schema will reach them: the mapping is the dispatch.
    assert VALIDATORS[definition.kind].coerce(definition, raw) == expected


@pytest.mark.parametrize(
    ("definition", "raw"),
    [
        (NUMBER, "pretty big"),
        (TOLERANCE, "7%"),
        (NOTES, "x" * (MAX_TEXT_LENGTH + 1)),
        (ROHS, "true"),
    ],
)
def test_each_kind_refuses_what_it_cannot_store_and_names_the_attribute(
    definition: AttributeSpec, raw: object
) -> None:
    # The key is in every message because the web renders the 422 next to its field.
    with pytest.raises(CatalogError, match=str(definition.key)):
        VALIDATORS[definition.kind].coerce(definition, raw)


def test_every_kind_has_a_validator() -> None:
    # A fifth kind is a fifth validator and nothing else; this is the test that says so.
    assert set(VALIDATORS) == set(AttributeKind)


def test_a_bool_attribute_takes_booleans_and_refuses_the_string_true() -> None:
    # The client sends JSON, where true is a literal: a string here is a client bug.
    assert BoolValidator().coerce(ROHS, False) is False
    with pytest.raises(CatalogError, match="rohs takes true or false"):
        BoolValidator().coerce(ROHS, "true")


def test_the_enum_message_lists_the_options_it_would_have_taken() -> None:
    with pytest.raises(CatalogError) as rejection:
        EnumValidator().coerce(TOLERANCE, "7%")

    assert "1%, 5%, 10%" in str(rejection.value)


def test_an_enum_refuses_a_value_that_is_not_a_string() -> None:
    with pytest.raises(CatalogError, match="tolerance takes one of"):
        EnumValidator().coerce(TOLERANCE, 5)


def test_a_number_accepts_a_trailing_unit_that_is_the_attributes_own() -> None:
    assert NumberValidator().coerce(CAPACITANCE, "100nF") == SiValue(Decimal("1E-7"))


def test_a_number_refuses_a_trailing_unit_that_is_another_quantitys() -> None:
    # 100nH is an inductance; on a farad attribute it is a typo worth stopping.
    with pytest.raises(InvalidNumberError, match=r"capacitance: .*in F"):
        NumberValidator().coerce(CAPACITANCE, "100nH")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("4k7", "4700"),
        (4700, "4700"),
        (-40, "-40"),
        (0.1, "0.1"),
        (Decimal("1E-7"), "0.0000001"),
        # A value already read once: review() coerces stored values again on every read.
        (SiValue(Decimal("1E-7")), "0.0000001"),
    ],
)
def test_a_number_reads_every_json_shape_exactly(raw: object, expected: str) -> None:
    assert NumberValidator().coerce(NUMBER, raw).value == Decimal(expected)


@pytest.mark.parametrize("raw", [True, None, ["4k7"], {"value": 1}])
def test_a_number_refuses_what_was_never_a_number(raw: object) -> None:
    # True first: a bool is an int in Python, so a switch would otherwise store 1.
    with pytest.raises(InvalidNumberError, match="resistance takes a number"):
        NumberValidator().coerce(NUMBER, raw)


def test_text_accepts_its_cap_after_trimming_and_refuses_one_character_more() -> None:
    capped = "x" * MAX_TEXT_LENGTH

    assert TextValidator().coerce(NOTES, f"  {capped}  ") == capped
    with pytest.raises(CatalogError, match=f"at most {MAX_TEXT_LENGTH} characters"):
        TextValidator().coerce(NOTES, "x" * (MAX_TEXT_LENGTH + 1))


def test_text_refuses_a_value_that_is_not_text() -> None:
    with pytest.raises(CatalogError, match="notes takes text, not int"):
        TextValidator().coerce(NOTES, 5)
