"""The wiring rules and the order of their findings (12-wiring-validation)."""

import random
from collections.abc import Mapping
from uuid import uuid7

from hypothesis import given
from hypothesis import strategies as st

from support.bom import a_revision, facts_of
from support.netlist import DESIGNATOR_POOL, PIN_POOL, a_net, content_of, net_contents
from wiredex.projects.domain.netlist import (
    NetContent,
    Netlist,
    PinReference,
    Resolution,
    ResolutionState,
)
from wiredex.projects.domain.pins import PinFacts, PinType
from wiredex.projects.domain.shortage import PartFacts
from wiredex.projects.domain.values import PartId
from wiredex.projects.domain.wiring import (
    RULES,
    FindingCode,
    PartsWithoutPinout,
    Severity,
    UnresolvedReferences,
    WiringFacts,
    check_wiring,
)

REVISION = a_revision()
PARTS: dict[str, PartFacts] = {
    str(designator): facts_of(PartId(uuid7()), f"Part {designator}")
    for designator in DESIGNATOR_POOL
}


def netlist_of(*contents: NetContent) -> Netlist:
    netlist = Netlist(REVISION.id)
    for content in contents:
        netlist = netlist.with_net(a_net(REVISION, content))
    return netlist


def facts(
    netlist: Netlist,
    states: Mapping[str, ResolutionState] = {},
    pins: Mapping[str, PinFacts] = {},
) -> WiringFacts:
    """Each reference resolved as `states` says, resolved by default, with its designator's part."""
    resolutions: dict[PinReference, Resolution] = {}
    for net in netlist.nets:
        for reference in net.content.pins:
            state = states.get(str(reference), ResolutionState.RESOLVED)
            part = None if state in _PARTLESS else PARTS[str(reference.designator)]
            pin = pins.get(str(reference)) if state is ResolutionState.RESOLVED else None
            if state is ResolutionState.RESOLVED and pin is None:
                pin = PinFacts(reference.pin, f"P{reference.pin}", PinType.IO)
            resolutions[reference] = Resolution(reference, state, part, pin)
    return WiringFacts(netlist, resolutions)


_PARTLESS = {ResolutionState.UNKNOWN_DESIGNATOR, ResolutionState.UNKNOWN_PART}


class TestUnresolvedReferences:
    def test_an_error_per_unresolved_reference_per_net_coded_by_its_state(self) -> None:
        netlist = netlist_of(content_of("SDA", "U1.1", "U2.2", "R1.1"), content_of("SCL", "U2.2"))
        found = list(
            UnresolvedReferences().check(
                facts(
                    netlist,
                    {
                        "U2.2": ResolutionState.UNKNOWN_DESIGNATOR,
                        "R1.1": ResolutionState.UNKNOWN_PIN,
                        "U1.1": ResolutionState.UNCHECKED,
                    },
                )
            )
        )
        assert [(f.code, str(f.references[0])) for f in found] == [
            (FindingCode.UNKNOWN_PIN, "R1.1"),
            (FindingCode.UNKNOWN_DESIGNATOR, "U2.2"),
            (FindingCode.UNKNOWN_DESIGNATOR, "U2.2"),
        ]
        assert {f.severity for f in found} == {Severity.ERROR}
        assert found[0].part == PARTS["R1"]


class TestPartsWithoutPinout:
    def test_one_warning_per_part_naming_its_designators_and_nets(self) -> None:
        netlist = netlist_of(content_of("3V3", "R1.1", "U1.1"), content_of("SDA", "R1.2"))
        (warning,) = PartsWithoutPinout().check(
            facts(netlist, {"R1.1": ResolutionState.UNCHECKED, "R1.2": ResolutionState.UNCHECKED})
        )
        assert (warning.code, warning.severity) == (FindingCode.NO_PINOUT, Severity.WARNING)
        assert warning.part == PARTS["R1"]
        assert warning.designators is not None
        assert warning.designators.text() == "R1"
        assert warning.net_ids == tuple(net.id for net in netlist.nets)
        assert [str(ref) for ref in warning.references] == ["R1.1", "R1.2"]


def test_no_nets_no_findings() -> None:
    assert check_wiring(facts(Netlist(REVISION.id))) == ()


# --- Properties -----------------------------------------------------------------------------

STATES = st.sampled_from(list(ResolutionState))
REFERENCE_TEXTS = [f"{designator}.{pin}" for designator in DESIGNATOR_POOL for pin in PIN_POOL]


@st.composite
def wirings(draw: st.DrawFn) -> WiringFacts:
    contents = draw(st.lists(net_contents, max_size=6, unique_by=lambda c: c.name.fold()))
    netlist = netlist_of(*contents)
    states = {text: draw(STATES) for text in REFERENCE_TEXTS}
    return facts(netlist, states)


# Property 1, for these two rules: each finds exactly its own case.
@given(wirings())
def test_unresolved_finds_exactly_the_unresolved_pairs(wiring: WiringFacts) -> None:
    expected = {
        (net.id, reference)
        for net in wiring.netlist.nets
        for reference in net.content.pins
        if wiring.resolution(reference).state.unresolved
    }
    found = {(f.net_ids[0], f.references[0]) for f in UnresolvedReferences().check(wiring)}
    assert found == expected


@given(wirings())
def test_no_pinout_finds_exactly_the_parts_with_an_unchecked_reference(
    wiring: WiringFacts,
) -> None:
    expected = {
        wiring.resolution(reference).part
        for net in wiring.netlist.nets
        for reference in net.content.pins
        if wiring.resolution(reference).state is ResolutionState.UNCHECKED
    }
    assert {f.part for f in PartsWithoutPinout().check(wiring)} == expected


# Property 3: the order is total, errors first, and follows the nets' order.
@given(wirings(), st.randoms())
def test_findings_come_errors_first_then_by_rule_net_and_reference(
    wiring: WiringFacts, shuffler: random.Random
) -> None:
    found = check_wiring(wiring)
    position = {net.id: index for index, net in enumerate(wiring.netlist.nets)}
    ranks = {type(rule): index for index, rule in enumerate(RULES)}
    keys = [
        (
            f.severity is Severity.WARNING,
            ranks[_rule_of(f.code)],
            min(position[net_id] for net_id in f.net_ids),
            f.references[0].sort_key(),
        )
        for f in found
    ]
    assert keys == sorted(keys)
    # Property 2's seed: the same findings whatever order the rules run in.
    shuffled = list(RULES)
    shuffler.shuffle(shuffled)
    assert sorted(map(repr, check_wiring(wiring, shuffled))) == sorted(map(repr, found))


def _rule_of(code: FindingCode) -> type:
    for rule in RULES:
        if rule.code is code or (
            isinstance(rule, UnresolvedReferences)
            and code
            in {FindingCode.UNKNOWN_DESIGNATOR, FindingCode.UNKNOWN_PART, FindingCode.UNKNOWN_PIN}
        ):
            return type(rule)
    raise AssertionError(code)
