"""Hypothesis strategies for pins and pinouts, shared by the pinout tests.

Cells are drawn as a datasheet prints them — numbers already upper-case, functions one token
— so every property is about the rule it names and not about text nobody would ever type.
"""

import string
from decimal import Decimal

from hypothesis import strategies as st

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


def rows_of(pinout: Pinout) -> list[RawPin]:
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
