"""A pin as a datasheet describes it: a number, a label, what it does, at which voltage.

The values a pin is made of, each validating itself in `__post_init__` and normalizing
through `object.__setattr__`, exactly as `values.py` does for the rest of the catalog
(ADR 0004). Only the number normalizes hard: it is the pin's identity on its part, so a BGA
ball typed `a1` and one typed `A1` have to be one pin. Labels and functions keep the case
the datasheet prints them in, because that case is information.

`Pin` and `Pinout`, at the end of the file, are what those values make up: a part's pins in
their saved order. Rules that need more than one pin — numbers unique, the table's caps —
live in the collection, because that is the only place that can see the whole table.
"""

import re
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from wiredex.catalog.domain.errors import (
    CatalogError,
    InvalidNumberError,
    InvalidPinFunctionError,
    InvalidPinLabelError,
    InvalidPinNumberError,
    InvalidPinoutError,
    InvalidPinTypeError,
    InvalidVoltageError,
    PinField,
)
from wiredex.catalog.domain.notation import format_si, normalize_symbols, parse_si
from wiredex.catalog.domain.values import SiValue, Unit

MAX_PIN_NUMBER_LENGTH = 16
# Letters, digits and the separators pin numbers are printed with: 1, A1, EP, P1.3, VDD+.
# No whitespace, because the netlist will reference a pin by this text.
_PIN_NUMBER = re.compile(rf"^[A-Z0-9_.+-]{{1,{MAX_PIN_NUMBER_LENGTH}}}$")


@dataclass(frozen=True, slots=True)
class PinNumber:
    """A pin's identity on its part: `1` on a DIP, `A1` on a BGA, `EP` for an exposed pad."""

    value: str

    def __post_init__(self) -> None:
        # Upper-cased, so `a1` and `A1` are the same ball (requirement 2.1); NFKC first, as
        # Unit does, so a full-width digit doesn't become a pin of its own.
        number = normalize_symbols(self.value).strip().upper()
        if not _PIN_NUMBER.match(number):
            raise InvalidPinNumberError(
                f"{self.value!r} is not a pin number like 1, A1 or EP: letters, digits and "
                f"_ . + -, up to {MAX_PIN_NUMBER_LENGTH} characters"
            )
        object.__setattr__(self, "value", number)

    def __str__(self) -> str:
        return self.value


MAX_PIN_LABEL_LENGTH = 40


@dataclass(frozen=True, slots=True)
class PinLabel:
    """What the datasheet calls the pin: `GPIO21`, `SDA`, `GND`. Labels repeat; numbers don't."""

    value: str

    def __post_init__(self) -> None:
        label = " ".join(self.value.split())
        if not 1 <= len(label) <= MAX_PIN_LABEL_LENGTH:
            raise InvalidPinLabelError(
                f"a pin label needs between 1 and {MAX_PIN_LABEL_LENGTH} characters"
            )
        object.__setattr__(self, "value", label)

    def __str__(self) -> str:
        return self.value


MAX_PIN_FUNCTION_LENGTH = 32
# One token: functions are typed space-separated and pasted slash-separated, so whitespace
# is where a function ends, never part of its name.
_PIN_FUNCTION = re.compile(rf"^\S{{1,{MAX_PIN_FUNCTION_LENGTH}}}$")


@dataclass(frozen=True, slots=True)
class PinFunction:
    """Another role the pin can take: `ADC1_CH6`, `SDA`, `TOUCH9`."""

    value: str

    def __post_init__(self) -> None:
        function = self.value.strip()
        if not _PIN_FUNCTION.match(function):
            raise InvalidPinFunctionError(
                f"{self.value!r} is not a pin function "
                f"(up to {MAX_PIN_FUNCTION_LENGTH} characters, no spaces)"
            )
        object.__setattr__(self, "value", function)

    def __str__(self) -> str:
        return self.value


class PinType(StrEnum):
    """What the pin is for, in the eight kinds requirement 2.6 allows.

    `INPUT` is separate from `IO` because ADR 0004's rule "input-only pins are not driven"
    needs to know which pins can't drive, and `NC` is a pin that must stay unconnected: both
    are rules the netlist will check, so they are types and not a note in a label.
    """

    POWER = "power"
    GROUND = "ground"
    IO = "io"
    INPUT = "input"
    OUTPUT = "output"
    ANALOG = "analog"
    NC = "nc"
    OTHER = "other"

    @classmethod
    def parse(cls, text: str) -> PinType:
        """The type as sent, or a refusal naming the eight.

        Spelled exactly: `PWR`, `I/O` and `N/C` are a pasted table's spellings, and the web
        maps them to these before saving (requirement 6.5), so that guessing stays where the
        owner can see and correct it.
        """
        try:
            return cls(text)
        except ValueError as error:
            raise InvalidPinTypeError(
                f"{text!r} is not a pin type — one of {', '.join(cls)}"
            ) from error


VOLT = Unit("V")
MAX_VOLTS = Decimal(1000)
# The convention boards are silkscreened with: the V stands in for the decimal point, so 3V3
# is 3.3 and 1V8 is 1.8, the way `1R5` does for resistors. parse_si can't read it (V is a
# unit, not a prefix), so it is read here, before anything else. A lower-case v is the same
# spelling typed in a hurry, and unambiguous: v is no SI prefix.
_BOARD_VOLTAGE = re.compile(r"^([+-]?\d+)[Vv](\d+)$")


@dataclass(frozen=True, slots=True)
class VoltageLevel:
    """A pin's supply or logic level, exact and in volts: 3.3, 1.8, -12, 0.5 for 500 mV.

    Decimal, as attribute numbers are, so 3V3 and 3.3 compare exactly equal and the value
    reaches a `numeric` column without a float rounding it on the way.
    """

    value: Decimal

    def __post_init__(self) -> None:
        if not self.value.is_finite():
            raise InvalidVoltageError(f"{self.value} is not a finite voltage")
        if abs(self.value) > MAX_VOLTS:
            raise InvalidVoltageError(f"a voltage level stays within ±{MAX_VOLTS:f} V")

    @classmethod
    def parse(cls, text: str) -> VoltageLevel:
        """Reads the board convention first, then whatever engineering notation reads in volts.

        So `3V3`, `1V8` and `12V0` work next to `3.3`, `3.3V`, `5`, `-12V` and `500mV`, while
        `3.3A` is refused because the unit isn't this one (requirements 2.9 and 2.10).
        """
        cleaned = normalize_symbols(text).strip()
        board = _BOARD_VOLTAGE.match(cleaned)
        if board is not None:
            return cls(Decimal(f"{board[1]}.{board[2]}").normalize())
        try:
            return cls(parse_si(cleaned, VOLT).value)
        except InvalidNumberError as error:
            # parse_si explains itself in prefixes; the board spelling is what it can't know.
            raise InvalidVoltageError(
                f"{text!r} is not a voltage — write it in volts, like 3V3, 3.3V, 3.3 or 500mV"
            ) from error

    def display(self) -> str:
        """What the web shows, as it shows attribute numbers: `3.3V`, `1.8V`, `500mV`."""
        return format_si(SiValue(self.value), VOLT)

    def __str__(self) -> str:
        # Plain digits, never 1E+3: this text is the exact value that crosses the wire.
        return f"{self.value:f}"


@dataclass(frozen=True, slots=True)
class Pin:
    """One row of a pinout: the pin's number on the part, its name, its job, its level."""

    number: PinNumber
    label: PinLabel
    type: PinType
    functions: tuple[PinFunction, ...] = ()
    voltage: VoltageLevel | None = None

    def __post_init__(self) -> None:
        # The same function listed twice is a paste artefact, not a refusal (requirement 2.7).
        # Dropped here rather than in `Pinout.parse`, so no path can put one role on a pin
        # twice; `dict.fromkeys` and not a set, because the order is the datasheet's.
        object.__setattr__(self, "functions", tuple(dict.fromkeys(self.functions)))


@dataclass(frozen=True, slots=True)
class RawPin:
    """The untyped row a client sends, as a part's raw attribute map is.

    It sits in the domain for the same reason: turning text into values is a domain rule, and
    a table is refused by `Pinout.parse` or not at all.
    """

    number: str
    label: str
    type: str
    functions: Sequence[str] = ()
    voltage: str | None = None


class Pinout:
    """A part's pins in their saved order. Numbers are unique; labels may repeat.

    Replaced whole, never patched pin by pin, so "no two pins share a number" is checked in
    one place — here — and a half-saved pinout can't exist. The order is part of the value:
    two pinouts holding the same pins shuffled are not equal, because the table is read in
    the order it was typed (requirement 1.1).
    """

    MAX_PINS = 1024
    MAX_FUNCTIONS_PER_PIN = 16

    __slots__ = ("_pins",)

    def __init__(self, pins: Iterable[Pin] = ()) -> None:
        """The rules one pin can't see, checked on every path into a pinout.

        `parse` is the way in from a client, and the repository the way in from the database;
        both end here, so neither can build a pinout the other would refuse.
        """
        self._pins: tuple[Pin, ...] = tuple(pins)
        self._check_size(len(self._pins))
        first_row: dict[str, int] = {}
        for row, pin in enumerate(self._pins, start=1):
            self._check_functions(pin, row)
            first = first_row.setdefault(pin.number.value, row)
            if first != row:
                # The later row, and the earlier one in the message: fixing a duplicate means
                # looking at the pair (requirement 3.2).
                raise InvalidPinoutError(
                    f"pin {pin.number} is already row {first}", row=row, field=PinField.NUMBER
                )

    @classmethod
    def parse(cls, rows: Sequence[RawPin]) -> Pinout:
        """The rows a client sent, as pins, refusing the first one that breaks a rule."""
        # The size first: a pasted spreadsheet of ten thousand rows is refused as a whole, and
        # reading row three of it would answer the wrong question (requirement 3.3).
        cls._check_size(len(rows))
        return cls(_read_pin(raw, row) for row, raw in enumerate(rows, start=1))

    @classmethod
    def empty(cls) -> Pinout:
        """A part with no pins: what reading an empty pinout answers, never a 404."""
        return cls()

    def __iter__(self) -> Iterator[Pin]:
        return iter(self._pins)

    def __len__(self) -> int:
        return len(self._pins)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Pinout):
            return NotImplemented
        # What `ReplacePinout` compares to decide whether a save changes anything at all.
        return self._pins == other._pins

    def __hash__(self) -> int:
        # The tuple is built once and never edited, so equal pinouts hash alike, as they must.
        return hash(self._pins)

    def __repr__(self) -> str:
        return f"Pinout({list(self._pins)!r})"

    @classmethod
    def _check_size(cls, pins: int) -> None:
        if pins > cls.MAX_PINS:
            # No row: the pinout as a whole is what's wrong (requirements 2.12 and 3.3).
            raise InvalidPinoutError(f"a pinout has at most {cls.MAX_PINS} pins")

    @classmethod
    def _check_functions(cls, pin: Pin, row: int) -> None:
        if len(pin.functions) > cls.MAX_FUNCTIONS_PER_PIN:
            raise InvalidPinoutError(
                f"a pin has at most {cls.MAX_FUNCTIONS_PER_PIN} alternate functions",
                row=row,
                field=PinField.FUNCTIONS,
            )


def _read_pin(raw: RawPin, row: int) -> Pin:
    """One row as typed values, every refusal carrying the row and the cell it came from."""
    with _pointing_at(row, PinField.NUMBER):
        number = PinNumber(raw.number)
    with _pointing_at(row, PinField.LABEL):
        label = PinLabel(raw.label)
    with _pointing_at(row, PinField.TYPE):
        kind = PinType.parse(raw.type)
    with _pointing_at(row, PinField.FUNCTIONS):
        functions = tuple(PinFunction(function) for function in raw.functions)
    with _pointing_at(row, PinField.VOLTAGE):
        voltage = _read_voltage(raw.voltage)
    return Pin(number, label, kind, functions, voltage)


def _read_voltage(text: str | None) -> VoltageLevel | None:
    """Nothing typed is no level at all, which a pin is allowed to have (requirement 2.11)."""
    if text is None or not text.strip():
        return None
    return VoltageLevel.parse(text)


@contextmanager
def _pointing_at(row: int, field: PinField) -> Iterator[None]:
    """Turns a value's own refusal into one that knows which cell of the table it came from."""
    try:
        yield
    except CatalogError as error:
        raise InvalidPinoutError(str(error), row=row, field=field) from error
