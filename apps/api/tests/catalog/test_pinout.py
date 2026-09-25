import string
from collections.abc import Callable, Sequence
from dataclasses import replace
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from wiredex.catalog.domain.errors import (
    InvalidPinFunctionError,
    InvalidPinLabelError,
    InvalidPinNumberError,
    InvalidPinoutError,
    InvalidPinTypeError,
    InvalidVoltageError,
    PinField,
)
from wiredex.catalog.domain.notation import SIGNIFICANT_DIGITS
from wiredex.catalog.domain.pinout import (
    MAX_PIN_FUNCTION_LENGTH,
    MAX_PIN_LABEL_LENGTH,
    MAX_PIN_NUMBER_LENGTH,
    MAX_VOLTS,
    Pin,
    PinFunction,
    PinLabel,
    PinNumber,
    Pinout,
    PinType,
    RawPin,
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


def _row(
    number: str,
    label: str = "IO",
    kind: str = "io",
    functions: Sequence[str] = (),
    voltage: str | None = None,
) -> RawPin:
    """A row a client could have sent, so a test spells out only the cell it is about."""
    return RawPin(number=number, label=label, type=kind, functions=functions, voltage=voltage)


def test_a_pinout_keeps_the_order_its_rows_were_sent_in() -> None:
    # Requirement 1.1: the order is the table, not something to sort by number.
    pinout = Pinout.parse([_row("3"), _row("1"), _row("EP")])
    assert [str(pin.number) for pin in pinout] == ["3", "1", "EP"]
    assert len(pinout) == 3


def test_parse_stores_what_each_value_normalizes_to() -> None:
    (pin,) = Pinout.parse(
        [RawPin(number=" a1 ", label="  SDI  ", type="io", functions=[" SDA "], voltage=" 3V3 ")]
    )
    assert str(pin.number) == "A1"
    assert str(pin.label) == "SDI"
    assert [str(function) for function in pin.functions] == ["SDA"]
    assert pin.voltage == VoltageLevel.parse("3.3")


def test_a_part_with_two_grounds_is_a_pinout_like_any_other() -> None:
    # Requirement 2.5: a BME280 really has two GND pins, so labels repeat and numbers don't.
    pinout = Pinout.parse([_row("1", "GND", "ground"), _row("7", "GND", "ground")])
    assert [str(pin.label) for pin in pinout] == ["GND", "GND"]


def test_an_exact_repeat_of_a_function_is_dropped_not_refused() -> None:
    # Requirement 2.7: pasting SDA twice onto one pin is an artefact of the paste, not an error.
    (pin,) = Pinout.parse([_row("3", "SDI", functions=["SDA", "MOSI", "SDA"])])
    assert [str(function) for function in pin.functions] == ["SDA", "MOSI"]


def test_functions_differing_in_case_are_two_functions() -> None:
    (pin,) = Pinout.parse([_row("3", "SDI", functions=["SDA", "sda"])])
    assert [str(function) for function in pin.functions] == ["SDA", "sda"]


def test_a_repeated_number_is_refused_naming_both_rows() -> None:
    numbers = ["1", "2", "5", "3", "4", "6", "7", "8", "9", "10", "11", "5"]
    with pytest.raises(InvalidPinoutError) as refused:
        Pinout.parse([_row(number) for number in numbers])
    # Requirement 3.2: the later row is the one to fix, and the earlier one is why.
    assert str(refused.value) == "row 12: pin 5 is already row 3"
    assert refused.value.row == 12
    assert refused.value.field is PinField.NUMBER


def test_one_ball_typed_in_two_cases_is_one_number_twice() -> None:
    with pytest.raises(InvalidPinoutError) as refused:
        Pinout.parse([_row("a1"), _row("A1")])
    assert str(refused.value) == "row 2: pin A1 is already row 1"


def test_a_pinout_accepts_its_cap_and_refuses_one_pin_more() -> None:
    at_cap = [_row(str(number)) for number in range(1, Pinout.MAX_PINS + 1)]
    assert len(Pinout.parse(at_cap)) == Pinout.MAX_PINS

    with pytest.raises(InvalidPinoutError) as refused:
        Pinout.parse([*at_cap, _row("EP")])
    # Requirements 2.12 and 3.3: the table as a whole is too big, so no row is to blame.
    assert str(refused.value) == f"a pinout has at most {Pinout.MAX_PINS} pins"
    assert refused.value.row is None
    assert refused.value.field is None


def test_a_pin_accepts_sixteen_functions_and_refuses_a_seventeenth() -> None:
    at_cap = [f"F{index}" for index in range(Pinout.MAX_FUNCTIONS_PER_PIN)]
    (pin,) = Pinout.parse([_row("1", functions=at_cap)])
    assert len(pin.functions) == Pinout.MAX_FUNCTIONS_PER_PIN

    with pytest.raises(InvalidPinoutError) as refused:
        Pinout.parse([_row("1"), _row("2", functions=[*at_cap, "ONE_MORE"])])
    assert refused.value.row == 2
    assert refused.value.field is PinField.FUNCTIONS
    assert "at most 16 alternate functions" in str(refused.value)


@pytest.mark.parametrize(
    ("broken", "field", "reason"),
    [
        (_row("A 1"), PinField.NUMBER, "is not a pin number"),
        (_row("1", label=""), PinField.LABEL, "a pin label needs"),
        (_row("1", kind="digital"), PinField.TYPE, "is not a pin type"),
        (_row("1", functions=["SD A"]), PinField.FUNCTIONS, "is not a pin function"),
        (_row("1", voltage="3.3A"), PinField.VOLTAGE, "is not a voltage"),
        (_row("1", voltage="2000"), PinField.VOLTAGE, "within"),
    ],
)
def test_a_refusal_from_any_value_names_its_row_and_its_cell(
    broken: RawPin, field: PinField, reason: str
) -> None:
    # Requirement 3.1: forty pasted rows and one bad cell means the editor is told which cell.
    with pytest.raises(InvalidPinoutError, match=reason) as refused:
        Pinout.parse([_row("98"), _row("99"), broken])
    assert refused.value.row == 3
    assert refused.value.field is field
    assert str(refused.value).startswith("row 3: ")


@pytest.mark.parametrize("voltage", [None, "", "   "])
def test_a_pin_with_nothing_in_its_voltage_cell_has_no_level(voltage: str | None) -> None:
    # Requirement 2.11: most pins have no level worth writing down.
    (pin,) = Pinout.parse([_row("1", voltage=voltage)])
    assert pin.voltage is None


def test_an_empty_pinout_is_a_pinout() -> None:
    # Requirement 1.2: a part with no pins reads as an empty list, never as a 404.
    empty = Pinout.empty()
    assert len(empty) == 0
    assert list(empty) == []
    assert empty == Pinout.parse([])


def test_pinouts_are_equal_when_they_hold_the_same_pins_in_the_same_order() -> None:
    rows = [_row("1", "GND", "ground"), _row("8", "VDD", "power", voltage="3V3")]
    assert Pinout.parse(rows) == Pinout.parse(rows)
    # What ReplacePinout compares, so "saved the same table again" has to be a no-op.
    assert Pinout.parse(rows) != Pinout.parse(list(reversed(rows)))
    assert Pinout.parse(rows) != rows
    # A pinout never changes once built, so equal ones have to hash alike.
    assert {Pinout.parse(rows), Pinout.parse(rows)} == {Pinout.parse(rows)}


def test_a_pinout_shows_its_pins_when_printed() -> None:
    # What a failing property test prints, so it has to name the pins and not the object id.
    assert repr(Pinout.parse([_row("1", "GND", "ground")])).startswith("Pinout([Pin(number=")


# --- Properties (design.md's correctness properties 1-4) ----------------------

# Realistic cells: a pin number is already upper-case on the silkscreen, and a function is
# one token. Generating what a datasheet prints keeps the properties about the rules.
PIN_NUMBER_CHARACTERS = string.ascii_uppercase + string.digits + "_.+-"
PIN_FUNCTION_CHARACTERS = string.ascii_uppercase + string.digits + "_+-"

pin_numbers = st.text(alphabet=PIN_NUMBER_CHARACTERS, min_size=1, max_size=MAX_PIN_NUMBER_LENGTH)
# Any text a label keeps, already collapsed: the filter only drops the all-whitespace ones.
pin_labels = (
    st.text(min_size=1, max_size=MAX_PIN_LABEL_LENGTH)
    .map(lambda text: " ".join(text.split()))
    .filter(lambda text: len(text) >= 1)
)
pin_functions = st.text(
    alphabet=PIN_FUNCTION_CHARACTERS, min_size=1, max_size=MAX_PIN_FUNCTION_LENGTH
)


@st.composite
def voltage_levels(draw: st.DrawFn) -> VoltageLevel:
    """Levels as a bench prints them: four significant digits at most, inside the ±1000 V cap.

    Four digits because that is what `display()` keeps; a fifth would round on the way out and
    property 3 would be about rounding instead of about reading a level back.
    """
    scale = draw(st.integers(min_value=-3, max_value=0))
    ceiling = min(10**SIGNIFICANT_DIGITS - 1, int(MAX_VOLTS.scaleb(-scale)))
    digits = draw(st.integers(min_value=-ceiling, max_value=ceiling))
    return VoltageLevel(Decimal(digits).scaleb(scale))


pins = st.builds(
    Pin,
    number=st.builds(PinNumber, pin_numbers),
    label=st.builds(PinLabel, pin_labels),
    type=st.sampled_from(PinType),
    functions=st.lists(
        st.builds(PinFunction, pin_functions), max_size=Pinout.MAX_FUNCTIONS_PER_PIN
    ).map(tuple),
    voltage=st.none() | voltage_levels(),
)


@st.composite
def pinouts(draw: st.DrawFn, min_size: int = 0, max_size: int = 8) -> Pinout:
    """Valid pinouts: pins in the order drawn, with numbers that can't collide."""
    return Pinout(
        draw(st.lists(pins, min_size=min_size, max_size=max_size, unique_by=lambda pin: pin.number))
    )


def _rows_of(pinout: Pinout) -> list[RawPin]:
    """The pinout as the wire carries it: every cell as the text the API sends and receives."""
    return [
        RawPin(
            number=str(pin.number),
            label=str(pin.label),
            type=pin.type.value,
            functions=[str(function) for function in pin.functions],
            voltage=None if pin.voltage is None else str(pin.voltage),
        )
        for pin in pinout
    ]


@given(pinouts())
def test_a_pinout_survives_its_own_wire_form(pinout: Pinout) -> None:
    """Property 1: parsing the rows a pinout serializes to gives that same pinout back.

    **Validates: Requirements 1.1, 2.1, 2.4, 2.7, 2.9**
    """
    read_back = Pinout.parse(_rows_of(pinout))

    assert list(read_back) == list(pinout)
    assert read_back == pinout


# Few spellings, so a collision is likely, and each one normalizes: whether two rows share a
# number is a question about the normalized text, not the typed text.
duplicate_prone_numbers = st.sampled_from(["1", "2", "3", "a1", "A1", " a1", "ep", "EP", "eP"])


@given(st.lists(duplicate_prone_numbers, max_size=10))
def test_a_pinout_is_refused_exactly_when_a_number_repeats(numbers: list[str]) -> None:
    """Property 2: parse succeeds iff no two numbers match once normalized; it names the later.

    **Validates: Requirements 2.1, 2.3, 3.2**
    """
    normalized = [PinNumber(number).value for number in numbers]
    repeat = _first_repeat(normalized)

    if repeat is None:
        assert [str(pin.number) for pin in Pinout.parse([_row(n) for n in numbers])] == normalized
        return
    later, first = repeat
    with pytest.raises(InvalidPinoutError) as refused:
        Pinout.parse([_row(number) for number in numbers])
    assert refused.value.row == later
    assert refused.value.field is PinField.NUMBER
    assert str(refused.value) == f"row {later}: pin {normalized[later - 1]} is already row {first}"


def _first_repeat(numbers: Sequence[str]) -> tuple[int, int] | None:
    """The 1-based rows of the first colliding pair: the later row, then the earlier one."""
    first_row: dict[str, int] = {}
    for row, number in enumerate(numbers, start=1):
        if number in first_row:
            return row, first_row[number]
        first_row[number] = row
    return None


@given(voltage_levels())
def test_a_voltage_reads_back_from_the_way_it_is_written(voltage: VoltageLevel) -> None:
    """Property 3: a level parses back from its display form and from its board spelling.

    **Validates: Requirements 2.9, 2.13**
    """
    assert VoltageLevel.parse(voltage.display()) == voltage
    assert VoltageLevel.parse(_board_spelling(voltage)) == voltage


def _board_spelling(voltage: VoltageLevel) -> str:
    """How a silkscreen prints the level: 3.3 is 3V3, 12 is 12V0, -0.5 is -0V5."""
    whole, _, fraction = str(voltage).partition(".")
    return f"{whole}V{fraction or '0'}"


# One cell broken per way a cell can break, so the field a refusal names is checked against
# the field that was actually broken and not against a guess.
BREAKAGES: tuple[tuple[PinField, Callable[[RawPin], RawPin]], ...] = (
    (PinField.NUMBER, lambda raw: replace(raw, number="A 1")),
    (PinField.NUMBER, lambda raw: replace(raw, number="")),
    (PinField.LABEL, lambda raw: replace(raw, label="   ")),
    (PinField.LABEL, lambda raw: replace(raw, label="x" * (MAX_PIN_LABEL_LENGTH + 1))),
    (PinField.TYPE, lambda raw: replace(raw, type="digital")),
    (PinField.FUNCTIONS, lambda raw: replace(raw, functions=["SD A"])),
    (PinField.FUNCTIONS, lambda raw: replace(raw, functions=["F" * (MAX_PIN_FUNCTION_LENGTH + 1)])),
    (
        PinField.FUNCTIONS,
        lambda raw: replace(
            raw, functions=[f"F{index}" for index in range(Pinout.MAX_FUNCTIONS_PER_PIN + 1)]
        ),
    ),
    (PinField.VOLTAGE, lambda raw: replace(raw, voltage="3.3A")),
    (PinField.VOLTAGE, lambda raw: replace(raw, voltage="2000")),
)


@st.composite
def tables_with_one_broken_row(draw: st.DrawFn) -> tuple[list[RawPin], int, PinField]:
    """A valid table with one cell of one row broken: the rows, that row's number, that cell."""
    rows = _rows_of(draw(pinouts(min_size=1)))
    at = draw(st.integers(min_value=0, max_value=len(rows) - 1))
    field, break_the_cell = draw(st.sampled_from(BREAKAGES))
    rows[at] = break_the_cell(rows[at])
    return rows, at + 1, field


@given(tables_with_one_broken_row())
def test_a_refusal_names_the_row_that_caused_it(
    broken: tuple[list[RawPin], int, PinField],
) -> None:
    """Property 4: one broken cell at row i is refused as row i, naming that cell.

    **Validates: Requirements 3.1**
    """
    rows, row, field = broken

    with pytest.raises(InvalidPinoutError) as refused:
        Pinout.parse(rows)

    assert refused.value.row == row
    assert refused.value.field is field
    assert str(refused.value).startswith(f"row {row}: ")
