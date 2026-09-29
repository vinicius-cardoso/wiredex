import string
from itertools import pairwise

import pytest
from hypothesis import given
from hypothesis import strategies as st

from support.bom import designators
from wiredex.projects.domain.designators import Designator
from wiredex.projects.domain.errors import InvalidPinReferenceError
from wiredex.projects.domain.netlist import PinReference, TypedReference, parse_pin_list
from wiredex.projects.domain.pins import PinNumber

pin_numbers = st.text(string.ascii_uppercase + string.digits + "_.+-", min_size=1, max_size=16).map(
    PinNumber
)


class TestTypedReference:
    @pytest.mark.parametrize(
        ("text", "designator", "pin"),
        [("U1.21", "U1", "21"), (" u2.sda ", "U2", "sda"), ("U3.P1.3", "U3", "P1.3")],
    )
    def test_splits_at_the_first_dot(self, text: str, designator: str, pin: str) -> None:
        typed = TypedReference.parse(text)
        assert (str(typed.designator), typed.pin) == (designator, pin)

    @pytest.mark.parametrize("text", ["U1", "U1.", ".21", "1U.21", "U1A.3", ""])
    def test_refuses_what_isnt_a_reference_naming_it(self, text: str) -> None:
        with pytest.raises(InvalidPinReferenceError) as refused:
            TypedReference.parse(text)
        assert refused.value.item == text

    def test_as_stored_takes_the_pin_as_a_number_when_it_is_one(self) -> None:
        assert str(TypedReference.parse("u1.a1").as_stored()) == "U1.A1"
        assert TypedReference.parse("U5.GND/ADJ").as_stored() is None


class TestPinList:
    def test_reads_commas_and_whitespace(self) -> None:
        typed = parse_pin_list("U1.21, U2.SDA\tR1.2,,  C1.1 ")
        assert [item.text for item in typed] == ["U1.21", "U2.SDA", "R1.2", "C1.1"]

    def test_blank_text_is_no_references(self) -> None:
        assert parse_pin_list("  , ") == ()


# Property 2: a pin reference is its grammar, and its text is a fixpoint.
@given(designators, pin_numbers)
def test_a_reference_reads_back_from_its_text(designator: Designator, pin: PinNumber) -> None:
    reference = PinReference(designator, pin)
    typed = TypedReference.parse(str(reference))
    assert typed.designator == designator
    assert typed.as_stored() == reference


# Property 4: canonical order is designator, then natural pin order.
@given(st.lists(st.tuples(designators, pin_numbers), max_size=20))
def test_canonical_order_is_designator_then_natural_pin(
    pairs: list[tuple[Designator, PinNumber]],
) -> None:
    references = [PinReference(designator, pin) for designator, pin in pairs]
    ordered = sorted(references, key=PinReference.sort_key)
    for before, after in pairwise(ordered):
        assert before.designator <= after.designator
        if before.designator == after.designator:
            assert before.pin.sort_key() <= after.pin.sort_key()
