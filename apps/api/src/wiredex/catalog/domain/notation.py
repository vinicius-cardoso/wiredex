"""Engineering notation: the only way a number enters the catalog domain.

Pure functions over Decimal, because two spellings of the same magnitude have to compare
exactly equal (4k7 == 4700) and float would make 100n land next to, not on, 1e-7.
"""

import re
import unicodedata
from decimal import ROUND_HALF_UP, Decimal

from wiredex.catalog.domain.errors import InvalidNumberError
from wiredex.catalog.domain.values import SiValue, Unit

# Case matters: m is milli and M is mega. R is the resistor convention for "no prefix"
# (1R5 is 1.5) and u is the ASCII spelling of µ. K is absent on purpose: k is kilo,
# K is kelvin, and guessing which one was meant is how wrong values get stored.
_EXPONENT_BY_PREFIX = {
    "p": -12,
    "n": -9,
    "µ": -6,  # U+00B5 MICRO SIGN, what format_si prints
    "μ": -6,  # U+03BC GREEK SMALL LETTER MU, what phones type and NFKC turns µ into
    "u": -6,
    "m": -3,
    "R": 0,
    "k": 3,
    "M": 6,
    "G": 9,
    "T": 12,
}
# What format_si prints back: one symbol per exponent, µ over u, nothing over R.
_PREFIX_BY_EXPONENT = {-12: "p", -9: "n", -6: "µ", -3: "m", 0: "", 3: "k", 6: "M", 9: "G", 12: "T"}
MIN_PREFIX_EXPONENT = -12
MAX_PREFIX_EXPONENT = 12
SIGNIFICANT_DIGITS = 4

_PREFIXES = "".join(_EXPONENT_BY_PREFIX)
_DECIMAL = r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)"
# 4700, 4.7e3
_PLAIN = re.compile(rf"^{_DECIMAL}(?:[eE][+-]?\d+)?$")
# 10k, 100n, 2.2µ
_SUFFIXED = re.compile(rf"^({_DECIMAL})([{_PREFIXES}])$")
# 4k7, 2u2, 1R5: the prefix stands in for the decimal point
_INFIXED = re.compile(rf"^([+-]?\d+)([{_PREFIXES}])(\d+)$")
# Only to explain the rejection, never to accept it.
_KELVIN = re.compile(rf"^{_DECIMAL}K\d*$")

_EXAMPLES = "write it like 4k7, 4700 or 4.7e3"


def parse_si(text: str, unit: Unit | None = None) -> SiValue:
    """Reads engineering notation into SI base units, rejecting anything ambiguous."""
    cleaned = normalize_symbols(text).strip()
    number = _read(cleaned)
    if number is None:
        # The prefix reading goes first, so "10m" stays milli even on a metre attribute;
        # a trailing unit is only dropped when it is the attribute's own.
        without_unit = _drop_unit(cleaned, unit)
        number = None if without_unit is None else _read(without_unit)
    if number is None:
        raise InvalidNumberError(_explain(text, unit))
    return SiValue(number.normalize())


def normalize_symbols(text: str) -> str:
    """One spelling for look-alikes: µ and μ, the ohm sign and omega, full-width digits."""
    return unicodedata.normalize("NFKC", text)


def format_si(value: SiValue, unit: Unit | None = None) -> str:
    """Prints a value with the prefix that puts the mantissa in [1, 1000), four digits at most."""
    mantissa, exponent = _engineering(value.value)
    symbol = "" if unit is None else str(unit)
    return f"{mantissa.normalize():f}{_PREFIX_BY_EXPONENT[exponent]}{symbol}"


def _read(text: str) -> Decimal | None:
    if _PLAIN.match(text):
        return Decimal(text)
    suffixed = _SUFFIXED.match(text)
    if suffixed is not None:
        return Decimal(suffixed[1]).scaleb(_EXPONENT_BY_PREFIX[suffixed[2]])
    infixed = _INFIXED.match(text)
    if infixed is not None:
        return Decimal(f"{infixed[1]}.{infixed[3]}").scaleb(_EXPONENT_BY_PREFIX[infixed[2]])
    return None


def _drop_unit(text: str, unit: Unit | None) -> str | None:
    if unit is None:
        return None
    symbol = str(unit)
    if not text.endswith(symbol) or len(text) == len(symbol):
        return None
    return text[: -len(symbol)]


def _explain(text: str, unit: Unit | None) -> str:
    if _KELVIN.match(text.strip()):
        return f"{text!r}: K is kelvin, k is kilo — {_EXAMPLES}"
    if unit is not None:
        return f"{text!r} is not a number in {unit} — {_EXAMPLES}"
    return f"{text!r} is not a number — {_EXAMPLES}"


def _engineering(number: Decimal) -> tuple[Decimal, int]:
    if not number:
        return Decimal(0), 0
    exponent = _prefix_exponent(number)
    mantissa = _to_significant(number.scaleb(-exponent))
    if abs(mantissa) >= 1000 and exponent < MAX_PREFIX_EXPONENT:  # noqa: PLR2004  the [1, 1000) rule
        # Rounding pushed the mantissa out of range, as 999.99 does: step up a prefix.
        exponent += 3
        mantissa = _to_significant(number.scaleb(-exponent))
    return mantissa, exponent


def _prefix_exponent(number: Decimal) -> int:
    # Outside p..T the mantissa leaves [1, 1000) rather than inventing a prefix nobody reads.
    multiple_of_three = number.adjusted() // 3 * 3
    return max(MIN_PREFIX_EXPONENT, min(MAX_PREFIX_EXPONENT, multiple_of_three))


def _to_significant(mantissa: Decimal) -> Decimal:
    step = Decimal(1).scaleb(mantissa.adjusted() - (SIGNIFICANT_DIGITS - 1))
    return mantissa.quantize(step, rounding=ROUND_HALF_UP)
