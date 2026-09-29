"""The wiring rules and the order of their findings (12-wiring-validation)."""

import random
from collections.abc import Mapping
from decimal import Decimal
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
from wiredex.projects.domain.pins import PinFacts, PinNumber, PinType
from wiredex.projects.domain.shortage import PartFacts
from wiredex.projects.domain.values import PartId
from wiredex.projects.domain.wiring import (
    DRIVES,
    RULES,
    FindingCode,
    InputOnlyUndriven,
    PartsWithoutPinout,
    PinReused,
    Severity,
    UnresolvedReferences,
    VoltageMismatch,
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


LEVELS = st.sampled_from([None, Decimal("3.3"), Decimal("3.30"), Decimal(5)])
TYPES = st.sampled_from(list(PinType))


@st.composite
def wirings(draw: st.DrawFn) -> WiringFacts:
    contents = draw(st.lists(net_contents, max_size=6, unique_by=lambda c: c.name.fold()))
    netlist = netlist_of(*contents)
    states = {text: draw(STATES) for text in REFERENCE_TEXTS}
    pins = {
        text: PinFacts(PinNumber(text.split(".")[1]), "P", draw(TYPES), (), draw(LEVELS))
        for text in REFERENCE_TEXTS
    }
    return facts(netlist, states, pins)


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


def _pin(text: str, kind: PinType, voltage: Decimal | None = None) -> PinFacts:
    return PinFacts(PinNumber(text.split(".")[1]), text, kind, (), voltage)


class TestPinReused:
    def test_an_error_per_reference_in_two_nets_naming_both(self) -> None:
        netlist = netlist_of(content_of("A", "U1.1", "R1.1"), content_of("B", "U1.1"))
        (finding,) = PinReused().check(facts(netlist, {"U1.1": ResolutionState.UNCHECKED}))
        assert finding.net_ids == tuple(net.id for net in netlist.nets)
        assert [str(ref) for ref in finding.references] == ["U1.1"]


class TestVoltageMismatch:
    def test_groups_the_references_by_level_and_reads_3v3_as_3_30(self) -> None:
        netlist = netlist_of(content_of("VCC", "U1.1", "U1.2", "U2.1", "R1.1"))
        pins = {
            "U1.1": _pin("U1.1", PinType.POWER, Decimal("3.3")),
            "U1.2": _pin("U1.2", PinType.POWER, Decimal(5)),
            "U2.1": _pin("U2.1", PinType.POWER, Decimal("3.30")),
        }
        (finding,) = VoltageMismatch().check(
            facts(netlist, {"R1.1": ResolutionState.UNCHECKED}, pins)
        )
        assert [
            (group.voltage, [str(r) for r in group.references]) for group in finding.levels
        ] == [
            (Decimal("3.3"), ["U1.1", "U2.1"]),
            (Decimal(5), ["U1.2"]),
        ]

    def test_one_level_and_pins_without_one_are_fine(self) -> None:
        netlist = netlist_of(content_of("VCC", "U1.1", "U1.2"))
        pins = {
            "U1.1": _pin("U1.1", PinType.POWER, Decimal("3.3")),
            "U1.2": _pin("U1.2", PinType.IO),
        }
        assert list(VoltageMismatch().check(facts(netlist, {}, pins))) == []


class TestInputOnlyUndriven:
    def test_the_greenhouse_soil_net_is_driven_through_its_divider(self) -> None:
        netlist = netlist_of(content_of("SOIL", "U1.5", "R1.2", "R2.1"))
        states = {"R1.2": ResolutionState.UNCHECKED, "R2.1": ResolutionState.UNCHECKED}
        pins = {"U1.5": _pin("U1.5", PinType.INPUT)}
        assert list(InputOnlyUndriven().check(facts(netlist, states, pins))) == []

    def test_an_input_only_pin_wired_only_to_another_input_is_undriven(self) -> None:
        netlist = netlist_of(content_of("CS", "U1.5", "U2.2"))
        pins = {"U1.5": _pin("U1.5", PinType.INPUT), "U2.2": _pin("U2.2", PinType.INPUT)}
        (finding,) = InputOnlyUndriven().check(facts(netlist, {}, pins))
        assert [str(ref) for ref in finding.references] == ["U1.5", "U2.2"]

    def test_a_net_of_one_reference_says_nothing(self) -> None:
        netlist = netlist_of(content_of("CS", "U1.5"))
        pins = {"U1.5": _pin("U1.5", PinType.INPUT)}
        assert list(InputOnlyUndriven().check(facts(netlist, {}, pins))) == []


# Property 1, for these three rules.
@given(wirings())
def test_pin_reused_finds_exactly_the_references_in_two_nets(wiring: WiringFacts) -> None:
    counts: dict[PinReference, int] = {}
    for net in wiring.netlist.nets:
        for reference in net.content.pins:
            counts[reference] = counts.get(reference, 0) + 1
    expected = {reference for reference, count in counts.items() if count > 1}
    assert {f.references[0] for f in PinReused().check(wiring)} == expected


@given(wirings())
def test_voltage_mismatch_finds_exactly_the_nets_with_two_levels(wiring: WiringFacts) -> None:
    expected = set()
    for net in wiring.netlist.nets:
        levels = {
            pin.voltage.normalize()
            for reference in net.content.pins
            if (pin := wiring.resolution(reference).pin) is not None and pin.voltage is not None
        }
        if len(levels) > 1:
            expected.add(net.id)
    assert {f.net_ids[0] for f in VoltageMismatch().check(wiring)} == expected


@given(wirings())
def test_input_only_finds_exactly_the_undriven_nets(wiring: WiringFacts) -> None:
    expected = set()
    for net in wiring.netlist.nets:
        resolutions = [wiring.resolution(reference) for reference in net.content.pins]
        driven = any(
            r.state is ResolutionState.UNCHECKED or (r.pin is not None and r.pin.type in DRIVES)
            for r in resolutions
        )
        has_input = any(r.pin is not None and r.pin.type is PinType.INPUT for r in resolutions)
        if len(resolutions) > 1 and has_input and not driven:
            expected.add(net.id)
    assert {f.net_ids[0] for f in InputOnlyUndriven().check(wiring)} == expected


# Property 2: rules are independent.
@given(wirings(), st.sets(st.sampled_from(range(len(RULES)))))
def test_any_subset_of_rules_finds_exactly_its_share(wiring: WiringFacts, chosen: set[int]) -> None:
    subset = [rule for index, rule in enumerate(RULES) if index in chosen]
    codes = {type(rule) for rule in subset}
    everything = check_wiring(wiring)
    assert check_wiring(wiring, subset) == tuple(f for f in everything if _rule_of(f.code) in codes)


# Property 5: levels compare exactly.
@given(st.lists(st.sampled_from(["3.3", "3.30", "3.300"]), min_size=2, max_size=5))
def test_one_level_however_it_is_written_is_no_mismatch(spellings: list[str]) -> None:
    pins_text = [f"U1.{index}" for index in range(1, len(spellings) + 1)]
    netlist = netlist_of(content_of("VCC", *pins_text))
    pins = {
        text: _pin(text, PinType.POWER, Decimal(spelling))
        for text, spelling in zip(pins_text, spellings, strict=True)
    }
    assert list(VoltageMismatch().check(facts(netlist, {}, pins))) == []
