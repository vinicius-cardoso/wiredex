"""A revision's netlist: its nets, the pin references they connect, and what those resolve to.

A pin reference is a BOM designator and a pin number, stored as text with no foreign key
(decision 2), so a BOM or pinout edit never blocks and never deletes wiring. What it names is
worked out at every read, `Resolution.of`, from the BOM, the catalog and the pinouts as they
stand then (decision 3); a write accepts a new reference only when it names a real pin
(decision 4).
"""

import re
import unicodedata
from dataclasses import dataclass

from wiredex.projects.domain.designators import Designator
from wiredex.projects.domain.errors import InvalidDesignatorError, InvalidPinReferenceError
from wiredex.projects.domain.pins import PinNumber

_SEPARATORS = re.compile(r"[,\s]+")


@dataclass(frozen=True, slots=True)
class PinReference:
    """A stored reference: a designator and the pin number it names (decision 2)."""

    designator: Designator
    pin: PinNumber

    def sort_key(self) -> tuple[Designator, tuple[tuple[tuple[int, int, str], ...], str]]:
        """Decision 8's order: by designator as 09 orders them, then by the pin's natural key."""
        return self.designator, self.pin.sort_key()

    def __str__(self) -> str:
        return f"{self.designator}.{self.pin}"


@dataclass(frozen=True, slots=True)
class TypedReference:
    """A reference as typed, split at its first dot (requirement 2.1): a designator and the
    pin's text, not yet a number. A designator never holds a dot (09's decision 5); a pin number
    may (`P1.3`), which is why the split is at the first one."""

    text: str
    designator: Designator
    pin: str

    @classmethod
    def parse(cls, text: str) -> TypedReference:
        """NFKC and trimmed, then `<designator>.<pin>`; `InvalidPinReferenceError` naming the
        text for no dot, a left half that isn't a designator, or an empty pin."""
        cleaned = unicodedata.normalize("NFKC", text).strip()
        left, dot, right = cleaned.partition(".")
        pin = right.strip()
        if not dot or not pin:
            raise _not_a_reference(text)
        try:
            designator = Designator.parse(left)
        except InvalidDesignatorError as error:
            raise _not_a_reference(text) from error
        return cls(text, designator, pin)

    def as_stored(self) -> PinReference | None:
        """The stored reference this spelling would be if its pin were taken as a number, or
        None when the pin isn't one: how an edit recognizes a reference its net already holds
        (requirement 3.8) without looking at the BOM or a pinout."""
        if not PinNumber.is_one(self.pin):
            return None
        return PinReference(self.designator, PinNumber(self.pin))


def parse_pin_list(text: str) -> tuple[TypedReference, ...]:
    """Items separated by commas or whitespace, each one pin reference (requirement 2.2)."""
    normalized = unicodedata.normalize("NFKC", text)
    return tuple(TypedReference.parse(item) for item in _SEPARATORS.split(normalized) if item)


def _not_a_reference(text: str) -> InvalidPinReferenceError:
    return InvalidPinReferenceError(
        f"{text!r} is not a pin reference like U1.21 or U2.SDA: a designator, a dot and a pin",
        item=text,
    )
