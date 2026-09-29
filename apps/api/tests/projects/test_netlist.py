import string
from itertools import pairwise
from uuid import uuid7

import pytest
from hypothesis import given
from hypothesis import strategies as st

from support.bom import a_revision, designators
from support.netlist import a_net, content_of, net_contents
from wiredex.projects.domain.designators import Designator
from wiredex.projects.domain.errors import (
    InvalidNetNameError,
    InvalidPinReferenceError,
    NetNameTakenError,
    NetNotFoundError,
    NoPinsError,
    RepeatedPinError,
    TooManyNetsError,
    TooManyPinsError,
)
from wiredex.projects.domain.netlist import (
    MAX_NET_NAME_LENGTH,
    MAX_NET_PINS,
    MAX_NETS,
    NetContent,
    Netlist,
    NetName,
    NetPins,
    PinReference,
    TypedReference,
    parse_pin_list,
)
from wiredex.projects.domain.pins import PinNumber
from wiredex.projects.domain.values import NetId

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


class TestNetName:
    @pytest.mark.parametrize(("text", "expected"), [(" SOIL  ADC ", "SOIL ADC"), ("3V3", "3V3")])
    def test_collapses_and_keeps_case(self, text: str, expected: str) -> None:
        assert str(NetName(text)) == expected

    @pytest.mark.parametrize("text", ["", "   ", "X" * 33, "SDA\x00", "a\u200bb"])
    def test_refuses_empty_long_or_unprintable_names(self, text: str) -> None:
        with pytest.raises(InvalidNetNameError):
            NetName(text)


# Property 1: a net name folds and its rules are exact.
@given(st.text(max_size=40))
def test_a_net_name_is_exactly_its_rules(text: str) -> None:
    collapsed = " ".join(text.split())
    valid = 1 <= len(collapsed) <= MAX_NET_NAME_LENGTH and collapsed.isprintable()
    try:
        name = NetName(text)
    except InvalidNetNameError:
        assert not valid
    else:
        assert valid
        assert name.value == collapsed
        assert name.fold() == collapsed.lower()


class TestNetPins:
    def test_sorts_and_writes_canonical_text(self) -> None:
        content = content_of("I2C", "U2.3", "U1.10", "U1.2", "R1.2")
        assert content.pins.text() == "R1.2, U1.2, U1.10, U2.3"

    def test_refuses_a_pin_twice(self) -> None:
        with pytest.raises(RepeatedPinError) as refused:
            content_of("SDA", "U1.25", "U1.25")
        assert refused.value.item == "U1.25"

    def test_refuses_none_and_too_many(self) -> None:
        with pytest.raises(NoPinsError):
            NetPins.of(())
        many = [f"U1.{number}" for number in range(1, MAX_NET_PINS + 2)]
        with pytest.raises(TooManyPinsError):
            content_of("GND", *many)


class TestNetlist:
    def test_refuses_a_name_another_net_holds_ignoring_case(self) -> None:
        revision = a_revision()
        first = a_net(revision, content_of("SDA", "U1.25"))
        netlist = Netlist(revision.id).with_net(first)
        with pytest.raises(NetNameTakenError) as refused:
            netlist.with_net(a_net(revision, content_of("sda", "U2.3")))
        assert (refused.value.net_id, refused.value.net) == (first.id, "SDA")

    def test_an_edit_keeps_its_own_name_and_place(self) -> None:
        revision = a_revision()
        first = a_net(revision, content_of("SDA", "U1.25"))
        second = a_net(revision, content_of("SCL", "U1.22"))
        netlist = Netlist(revision.id).with_net(first).with_net(second)
        edited = first.revised(content_of("sda", "U1.25", "R1.2"))
        assert netlist.replacing(edited).nets == (edited, second)

    def test_a_pin_may_sit_in_two_nets(self) -> None:
        revision = a_revision()
        netlist = Netlist(revision.id).with_net(a_net(revision, content_of("A", "U1.1")))
        netlist = netlist.with_net(a_net(revision, content_of("B", "U1.1")))
        assert len(netlist.nets) == 2

    def test_refuses_a_501st_net(self) -> None:
        revision = a_revision()
        nets = tuple(a_net(revision, content_of(f"N{index}", "U1.1")) for index in range(MAX_NETS))
        with pytest.raises(TooManyNetsError):
            Netlist(revision.id, nets).with_net(a_net(revision, content_of("ONE_MORE", "U1.1")))

    def test_a_net_of_another_revision_is_not_found(self) -> None:
        revision = a_revision()
        with pytest.raises(NetNotFoundError):
            Netlist(revision.id).net(NetId(uuid7()))


# Property 8 over the collection: its invariants hold under any adds, edits and removals.
@given(st.lists(st.tuples(st.sampled_from(["add", "edit", "remove"]), net_contents), max_size=25))
def test_a_netlist_keeps_its_invariants(steps: list[tuple[str, NetContent]]) -> None:
    revision = a_revision()
    netlist = Netlist(revision.id)
    for action, content in steps:
        try:
            if action == "add":
                netlist = netlist.with_net(a_net(revision, content))
            elif netlist.nets and action == "edit":
                netlist = netlist.replacing(netlist.nets[0].revised(content))
            elif netlist.nets:
                netlist = netlist.without(netlist.nets[-1].id)
        except NetNameTakenError:
            pass
        names = [net.content.name.fold() for net in netlist.nets]
        assert len(names) == len(set(names))
        assert len(netlist.nets) <= MAX_NETS
