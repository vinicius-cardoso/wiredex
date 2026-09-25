from decimal import Decimal

import pytest

from wiredex.catalog.domain.errors import InvalidNumberError
from wiredex.catalog.domain.notation import format_si, parse_si
from wiredex.catalog.domain.values import SiValue, Unit

OHM = Unit("Ω")
FARAD = Unit("F")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("4700", "4700"),
        ("4.7e3", "4700"),
        ("4.7E3", "4700"),
        ("4k7", "4700"),
        ("2u2", "0.0000022"),
        ("1R5", "1.5"),
        ("10k", "10000"),
        ("100n", "0.0000001"),
        ("2.2µ", "0.0000022"),
        ("-40", "-40"),
        ("-4k7", "-4700"),
        ("  10k  ", "10000"),
    ],
)
def test_every_accepted_spelling_reads_as_its_si_value(text: str, expected: str) -> None:
    assert parse_si(text).value == Decimal(expected)


@pytest.mark.parametrize(
    ("text", "unit", "expected"),
    [
        ("10kΩ", OHM, "10000"),
        ("100nF", FARAD, "0.0000001"),
        ("4k7Ω", OHM, "4700"),
        ("10k", OHM, "10000"),
    ],
)
def test_a_trailing_unit_that_matches_is_accepted_and_ignored(
    text: str, unit: Unit, expected: str
) -> None:
    assert parse_si(text, unit).value == Decimal(expected)


def test_ten_kilo_and_ten_thousand_are_the_same_value_exactly() -> None:
    assert parse_si("10k") == parse_si("10000")
    assert str(parse_si("10k")) == "10000"


@pytest.mark.parametrize("text", ["10K", "4K7", "0.5K"])
def test_uppercase_k_is_rejected_because_it_is_kelvin(text: str) -> None:
    with pytest.raises(InvalidNumberError, match="K is kelvin"):
        parse_si(text)


def test_a_kelvin_unit_still_accepts_its_own_symbol() -> None:
    # 300K on a kelvin attribute is a unit, not a prefix, so the K rule doesn't apply.
    assert parse_si("300K", Unit("K")).value == Decimal(300)


def test_a_trailing_unit_that_does_not_match_is_rejected() -> None:
    with pytest.raises(InvalidNumberError, match="in F"):
        parse_si("100nH", FARAD)


@pytest.mark.parametrize(
    "text", ["", "   ", "abc", "10 k", "1.2.3", "k10", "10kk", "--4", "4k7k", "1e", "R5", "4,7k"]
)
def test_garbage_is_rejected_with_an_example(text: str) -> None:
    with pytest.raises(InvalidNumberError, match="4k7"):
        parse_si(text)


def test_infinities_and_nans_never_become_values() -> None:
    with pytest.raises(InvalidNumberError):
        SiValue(Decimal("NaN"))
    with pytest.raises(InvalidNumberError):
        parse_si("Infinity")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("4700", "4.7k"),
        ("10000", "10k"),
        ("1E-7", "100n"),
        ("0.0000022", "2.2µ"),
        ("1.5", "1.5"),
        ("-40", "-40"),
        ("0", "0"),
        ("0.047", "47m"),
        ("1234567", "1.235M"),
        ("999.99", "1k"),
        ("1E+15", "1000T"),
        ("1E-15", "0.001p"),
    ],
)
def test_formatting_keeps_the_mantissa_under_a_thousand_with_four_digits(
    value: str, expected: str
) -> None:
    assert format_si(SiValue(Decimal(value))) == expected


def test_formatting_appends_the_unit_when_there_is_one() -> None:
    assert format_si(SiValue(Decimal("4700")), OHM) == "4.7kΩ"


@pytest.mark.parametrize(
    "text", ["4700", "4.7e3", "4k7", "2u2", "1R5", "10k", "100n", "2.2µ", "-40", "0", "47m"]
)
def test_parsing_a_formatted_value_gives_the_same_value_back(text: str) -> None:
    value = parse_si(text)
    assert parse_si(format_si(value)) == value


def test_the_round_trip_survives_the_unit() -> None:
    value = parse_si("100nF", FARAD)
    assert parse_si(format_si(value, FARAD), FARAD) == value


@pytest.mark.parametrize(
    ("text", "unit"),
    [
        ("2.2\u00b5", None),  # MICRO SIGN
        ("2.2\u03bc", None),  # GREEK SMALL LETTER MU, as phones type it
        ("2.2\u03bcF", Unit("F")),
        ("\uff12.\uff12\u00b5", None),  # full-width digits
    ],
)
def test_look_alike_micro_signs_and_digits_read_the_same(text: str, unit: Unit | None) -> None:
    assert parse_si(text, unit).value == Decimal("0.0000022")


def test_the_ohm_sign_and_omega_are_the_same_unit() -> None:
    ohm_sign, omega = Unit("\u2126"), Unit("\u03a9")

    assert ohm_sign == omega
    assert parse_si("10k\u2126", omega).value == Decimal(10000)
    assert parse_si("10k\u03a9", ohm_sign).value == Decimal(10000)
