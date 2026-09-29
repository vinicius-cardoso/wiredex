from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from wiredex.projects.domain.errors import InvalidPinReferenceError
from wiredex.projects.domain.pins import PartPins, PinFacts, PinNumber, PinType


def _pin(number: str, label: str, *functions: str, kind: PinType = PinType.IO) -> PinFacts:
    return PinFacts(PinNumber(number), label, kind, functions, Decimal("3.3"))


# A slice of the sample DevKitC's header: three grounds, a function on one pin only.
DEVKIT = PartPins(
    (
        _pin("1", "3V3", kind=PinType.POWER),
        _pin("14", "GND", kind=PinType.GROUND),
        _pin("20", "GND", kind=PinType.GROUND),
        _pin("22", "GPIO22", "SCL"),
        _pin("25", "GPIO21", "SDA"),
        _pin("26", "GND", kind=PinType.GROUND),
    )
)


class TestPinNumber:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [("a1", "A1"), (" 21 ", "21"), ("\uff21\uff11", "A1"), ("p1.3", "P1.3")],
    )
    def test_normalizes_as_catalog_does(self, text: str, expected: str) -> None:
        assert str(PinNumber(text)) == expected

    @pytest.mark.parametrize("text", ["", "A 1", "GND/ADJ", "X" * 17, "Ω"])
    def test_refuses_anything_else_naming_it(self, text: str) -> None:
        with pytest.raises(InvalidPinReferenceError) as refused:
            PinNumber(text)
        assert refused.value.item == text

    def test_orders_runs_of_digits_as_numbers(self) -> None:
        numbers = ["10", "B1", "2", "A10", "A2", "1", "EP"]
        ordered = sorted(numbers, key=lambda text: PinNumber(text).sort_key())
        assert ordered == ["1", "2", "10", "A2", "A10", "B1", "EP"]

    @given(st.integers(1, 10_000), st.integers(1, 10_000))
    def test_plain_numbers_order_as_integers(self, first: int, second: int) -> None:
        keys = PinNumber(str(first)).sort_key(), PinNumber(str(second)).sort_key()
        assert (keys[0] < keys[1]) == (first < second)


class TestMatching:
    def test_a_number_wins(self) -> None:
        assert [str(pin.number) for pin in DEVKIT.matching("25")] == ["25"]

    def test_a_label_is_matched_ignoring_case(self) -> None:
        assert [str(pin.number) for pin in DEVKIT.matching("gpio21")] == ["25"]

    def test_a_function_is_matched_when_no_label_is(self) -> None:
        assert [str(pin.number) for pin in DEVKIT.matching("sda")] == ["25"]

    def test_a_repeated_label_matches_every_pin_carrying_it(self) -> None:
        assert [str(pin.number) for pin in DEVKIT.matching("GND")] == ["14", "20", "26"]

    def test_nothing_matches_an_unknown_pin(self) -> None:
        assert DEVKIT.matching("99") == ()
        assert DEVKIT.matching("MOSI") == ()

    def test_a_label_that_is_a_valid_number_still_falls_back_to_labels(self) -> None:
        # 3V3 reads as a pin number, but no pin has it: the label is what it names.
        assert [str(pin.number) for pin in DEVKIT.matching("3v3")] == ["1"]
