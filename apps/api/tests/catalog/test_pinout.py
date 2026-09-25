from decimal import Decimal

import pytest

from wiredex.catalog.domain.errors import (
    InvalidPinFunctionError,
    InvalidPinLabelError,
    InvalidPinNumberError,
    InvalidPinTypeError,
    InvalidVoltageError,
)
from wiredex.catalog.domain.pinout import (
    MAX_PIN_FUNCTION_LENGTH,
    MAX_PIN_LABEL_LENGTH,
    MAX_PIN_NUMBER_LENGTH,
    PinFunction,
    PinLabel,
    PinNumber,
    PinType,
    VoltageLevel,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1", "1"),
        ("40", "40"),
        ("a1", "A1"),
        ("  A1  ", "A1"),
        ("ep", "EP"),
        ("p1.3", "P1.3"),
        ("VDD+", "VDD+"),
        ("gpio_2", "GPIO_2"),
        ("\uff41\uff11", "A1"),  # full-width, as a phone or a PDF copy types it
    ],
)
def test_pin_numbers_are_trimmed_and_upper_cased(text: str, expected: str) -> None:
    assert str(PinNumber(text)) == expected


def test_a_ball_typed_in_either_case_is_the_same_pin() -> None:
    # Requirement 2.1: the number is the pin's identity, so a1 and A1 must not be two pins.
    assert PinNumber("a1") == PinNumber("A1")


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "A 1",  # a number is one token: the netlist will reference it as text
        "A/1",
        "A#1",
        "pin@1",
        "1,2",
        "Ω1",
        "x" * (MAX_PIN_NUMBER_LENGTH + 1),
    ],
)
def test_pin_numbers_outside_the_character_set_are_refused(text: str) -> None:
    with pytest.raises(InvalidPinNumberError, match="is not a pin number"):
        PinNumber(text)


def test_pin_numbers_accept_their_cap() -> None:
    assert str(PinNumber("A" * MAX_PIN_NUMBER_LENGTH)) == "A" * MAX_PIN_NUMBER_LENGTH


def test_pin_labels_are_trimmed_collapsed_and_keep_their_case() -> None:
    # GPIO21 and VDDIO are the datasheet's spelling: lower-casing a label loses information.
    assert str(PinLabel("  GPIO21  ")) == "GPIO21"
    assert str(PinLabel("VDD   IO")) == "VDD IO"


def test_pin_labels_accept_their_cap_and_refuse_one_character_more() -> None:
    assert str(PinLabel("x" * MAX_PIN_LABEL_LENGTH)) == "x" * MAX_PIN_LABEL_LENGTH
    with pytest.raises(InvalidPinLabelError, match=f"between 1 and {MAX_PIN_LABEL_LENGTH}"):
        PinLabel("x" * (MAX_PIN_LABEL_LENGTH + 1))


@pytest.mark.parametrize("text", ["", "   ", "\t\n"])
def test_a_blank_label_is_never_a_label(text: str) -> None:
    with pytest.raises(InvalidPinLabelError):
        PinLabel(text)


def test_pin_functions_are_trimmed_and_keep_their_case() -> None:
    assert str(PinFunction("  ADC1_CH6  ")) == "ADC1_CH6"
    assert str(PinFunction("SDA")) == "SDA"


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "SD A",  # the editor splits functions on whitespace, so a space is two functions
        "SDA\tSCL",
        "x" * (MAX_PIN_FUNCTION_LENGTH + 1),
    ],
)
def test_pin_functions_with_whitespace_or_too_long_are_refused(text: str) -> None:
    with pytest.raises(InvalidPinFunctionError, match="is not a pin function"):
        PinFunction(text)


def test_pin_functions_accept_their_cap() -> None:
    assert str(PinFunction("x" * MAX_PIN_FUNCTION_LENGTH)) == "x" * MAX_PIN_FUNCTION_LENGTH


def test_the_pin_types_are_exactly_the_eight_of_the_glossary() -> None:
    assert [kind.value for kind in PinType] == [
        "power",
        "ground",
        "io",
        "input",
        "output",
        "analog",
        "nc",
        "other",
    ]
    # A StrEnum, so the type reaches JSON and the CHECK constraint as its own name.
    assert str(PinType.NC) == "nc"


@pytest.mark.parametrize("kind", list(PinType))
def test_every_pin_type_reads_back_from_its_own_name(kind: PinType) -> None:
    assert PinType.parse(kind.value) is kind


@pytest.mark.parametrize("text", ["", "POWER", "Power", "power ", "gpio", "vcc", "n/c", "digital"])
def test_anything_else_is_not_a_pin_type(text: str) -> None:
    # Pasted spellings (PWR, I/O, N/C) are mapped in the web, where the owner sees the guess.
    with pytest.raises(InvalidPinTypeError, match="is not a pin type"):
        PinType.parse(text)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("3.3", "3.3"),
        ("3.3V", "3.3"),
        ("3V3", "3.3"),
        ("3v3", "3.3"),
        ("1V8", "1.8"),
        ("12V0", "12"),
        ("5", "5"),
        ("3V", "3"),
        ("-12V", "-12"),
        ("-12V0", "-12"),
        ("500mV", "0.5"),
        ("0", "0"),
        ("  3V3  ", "3.3"),
        ("1000", "1000"),  # the cap itself, ±1000 V
        ("-1000", "-1000"),
    ],
)
def test_every_accepted_voltage_spelling_reads_as_its_value_in_volts(
    text: str, expected: str
) -> None:
    assert VoltageLevel.parse(text).value == Decimal(expected)


def test_the_same_level_spelled_three_ways_is_one_voltage() -> None:
    assert VoltageLevel.parse("3V3") == VoltageLevel.parse("3.3") == VoltageLevel.parse("3.3V")


@pytest.mark.parametrize(
    "text",
    [
        "3.3A",  # another unit is not a voltage, however well it reads
        "100nF",
        "abc",
        "",
        "   ",
        "3.3 V",
        "V3",
        "Infinity",
    ],
)
def test_text_that_is_not_a_voltage_is_refused(text: str) -> None:
    with pytest.raises(InvalidVoltageError, match="is not a voltage"):
        VoltageLevel.parse(text)


@pytest.mark.parametrize("text", ["2000", "-2000", "1001", "1001V0", "2kV"])
def test_a_level_beyond_a_thousand_volts_is_refused(text: str) -> None:
    # Requirement 2.10: a pin sits on a bench supply, not on a transmission line.
    with pytest.raises(InvalidVoltageError, match="within"):
        VoltageLevel.parse(text)


def test_infinities_and_nans_are_never_voltages() -> None:
    with pytest.raises(InvalidVoltageError, match="finite"):
        VoltageLevel(Decimal("NaN"))
    with pytest.raises(InvalidVoltageError, match="finite"):
        VoltageLevel(Decimal("Infinity"))


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        ("3V3", "3.3V"),
        ("1V8", "1.8V"),
        ("5", "5V"),
        ("-12V", "-12V"),
        ("500mV", "500mV"),
        ("0", "0V"),
    ],
)
def test_a_voltage_shows_the_way_a_schematic_prints_it(text: str, shown: str) -> None:
    assert VoltageLevel.parse(text).display() == shown


def test_a_voltage_crosses_the_wire_as_plain_exact_digits() -> None:
    assert str(VoltageLevel.parse("3V3")) == "3.3"
    assert str(VoltageLevel.parse("500mV")) == "0.5"
    # 1000 normalizes to 1E+3 as a Decimal; the wire never sees that.
    assert str(VoltageLevel.parse("1000")) == "1000"
