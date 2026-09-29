"""Pins as the netlist sees them: a number, and what catalog's pinout says about it (decision 13).

Projects can't import catalog's pin values, and a pin reference has to normalize its number
exactly as a pinout does, or a stored `U1.a1` would never find ball `A1`. So the grammar is
written here again, 02's to the letter, and a bootstrap test holds the two to each other over
generated text. `PinFacts` and `PartPins` are what `NetlistPins` answers, translated from
catalog's `Pin` by bootstrap.
"""

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from wiredex.projects.domain.errors import InvalidPinReferenceError

MAX_PIN_NUMBER_LENGTH = 16
# 02's grammar: letters, digits and the separators pin numbers are printed with (1, A1, EP,
# P1.3, VDD+). A dot may sit inside a number, which is why a reference splits at its first dot.
_PIN_NUMBER = re.compile(rf"^[A-Z0-9_.+-]{{1,{MAX_PIN_NUMBER_LENGTH}}}$")
_RUNS = re.compile(r"(\d+)")


@dataclass(frozen=True, slots=True)
class PinNumber:
    """A pin's identity on its part: NFKC, trimmed and upper-cased, as catalog's is."""

    value: str

    def __post_init__(self) -> None:
        number = unicodedata.normalize("NFKC", self.value).strip().upper()
        if not _PIN_NUMBER.match(number):
            raise InvalidPinReferenceError(
                f"{self.value!r} is not a pin number like 1, A1 or EP: letters, digits and "
                f"_ . + -, up to {MAX_PIN_NUMBER_LENGTH} characters",
                item=self.value,
            )
        object.__setattr__(self, "value", number)

    @classmethod
    def is_one(cls, text: str) -> bool:
        """Whether the text reads as a pin number, for the matching that tries a number first."""
        try:
            cls(text)
        except InvalidPinReferenceError:
            return False
        return True

    def sort_key(self) -> tuple[tuple[tuple[int, int, str], ...], str]:
        """Decision 8's order: runs of digits compared as numbers, so 2 < 10 and A2 < A10 < B1.

        The text itself breaks ties, so `02` and `2`, two pins of one part, still order.
        """
        runs = tuple(
            (0, int(run), "") if run.isdigit() else (1, 0, run)
            for run in _RUNS.split(self.value)
            if run
        )
        return runs, self.value

    def __str__(self) -> str:
        return self.value


class PinType(StrEnum):
    """02's eight pin types, as projects names them; bootstrap translates them by value."""

    POWER = "power"
    GROUND = "ground"
    IO = "io"
    INPUT = "input"
    OUTPUT = "output"
    ANALOG = "analog"
    NC = "nc"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class PinFacts:
    """One pin of a part's pinout: its number, label, type, functions and level."""

    number: PinNumber
    label: str
    type: PinType
    functions: tuple[str, ...] = ()
    voltage: Decimal | None = None


@dataclass(frozen=True, slots=True)
class PartPins:
    """One part's pinout, in its saved order. Only a part with pins has one: a part with none is
    absent from `NetlistPins.of_parts`, which is how "no pinout" is told apart (decision 3)."""

    pins: tuple[PinFacts, ...]

    def numbered(self, number: PinNumber) -> PinFacts | None:
        return next((pin for pin in self.pins if pin.number == number), None)

    def matching(self, typed: str) -> tuple[PinFacts, ...]:
        """Decision 4's order: the pin with this number; else the pins with this label; else the
        pins with this function. Labels and functions are compared case-folded, since `sda` and
        `SDA` name one role. Empty when nothing matches; several when a label or function
        repeats, as `GND` does."""
        text = unicodedata.normalize("NFKC", typed).strip()
        if PinNumber.is_one(text):
            found = self.numbered(PinNumber(text))
            if found is not None:
                return (found,)
        folded = text.casefold()
        labelled = tuple(pin for pin in self.pins if pin.label.casefold() == folded)
        if labelled:
            return labelled
        return tuple(
            pin
            for pin in self.pins
            if any(function.casefold() == folded for function in pin.functions)
        )
