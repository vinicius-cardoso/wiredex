"""A pin as a datasheet describes it: a number, a label, what it does, at which voltage.

The values a pin is made of, each validating itself in `__post_init__` and normalizing
through `object.__setattr__`, exactly as `values.py` does for the rest of the catalog
(ADR 0004). Only the number normalizes hard: it is the pin's identity on its part, so a BGA
ball typed `a1` and one typed `A1` have to be one pin. Labels and functions keep the case
the datasheet prints them in, because that case is information.
"""

import re
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from wiredex.catalog.domain.errors import (
    InvalidNumberError,
    InvalidPinFunctionError,
    InvalidPinLabelError,
    InvalidPinNumberError,
    InvalidPinTypeError,
    InvalidVoltageError,
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
