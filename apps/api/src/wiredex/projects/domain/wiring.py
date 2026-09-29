"""What is wrong with a revision's wiring: the rules, and the findings they report
(12-wiring-validation).

ADR 0004: validation is a list of independent rules, each returning errors and warnings. A rule
is a small class with a `code` and a `check`, and `RULES` is the tuple of them in their
reporting order (decision 1). A rule sees `WiringFacts` alone, the netlist and what each of its
references resolves to (11's `Resolution`), never another rule's findings, so adding a rule is
one class and one entry in `RULES`, the others unchanged (requirements 1.2, 11.1). Nothing here
is stored: findings are computed at every read, as the shortage report is (requirement 1.4).
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import ClassVar, Protocol

from wiredex.projects.domain.designators import Designators
from wiredex.projects.domain.netlist import Netlist, PinReference, Resolution, ResolutionState
from wiredex.projects.domain.pins import PinType
from wiredex.projects.domain.shortage import PartFacts
from wiredex.projects.domain.values import NetId, PartId


class Severity(StrEnum):
    """An error is something wrong or no longer matching; a warning is worth a look."""

    ERROR = "error"
    WARNING = "warning"


class FindingCode(StrEnum):
    UNKNOWN_DESIGNATOR = "unknown_designator"
    UNKNOWN_PART = "unknown_part"
    UNKNOWN_PIN = "unknown_pin"
    NO_PINOUT = "no_pinout"
    PIN_REUSED = "pin_reused"
    VOLTAGE_MISMATCH = "voltage_mismatch"
    INPUT_ONLY_UNDRIVEN = "input_only_undriven"


@dataclass(frozen=True, slots=True)
class VoltageGroup:
    """The references of a net at one voltage level, for a mismatch (requirement 4.1)."""

    voltage: Decimal
    references: tuple[PinReference, ...]


@dataclass(frozen=True, slots=True)
class Finding:
    """What a rule reports (decision 4): its code and severity, the nets it is about in netlist
    order, the references in canonical order, and what its sentence needs besides."""

    code: FindingCode
    severity: Severity
    net_ids: tuple[NetId, ...]
    references: tuple[PinReference, ...]
    part: PartFacts | None = None  # unknown_pin and no_pinout
    designators: Designators | None = None  # no_pinout
    levels: tuple[VoltageGroup, ...] = ()  # voltage_mismatch, lowest first


@dataclass(frozen=True, slots=True)
class WiringFacts:
    """All a rule may see: the nets in order, and what each stored reference resolves to."""

    netlist: Netlist
    resolutions: Mapping[PinReference, Resolution]

    def resolution(self, reference: PinReference) -> Resolution:
        return self.resolutions[reference]


class WiringRule(Protocol):
    """One independent check over a revision's wiring (Strategy, ADR 0004)."""

    code: ClassVar[FindingCode]

    def check(self, facts: WiringFacts) -> Iterable[Finding]: ...


_BY_STATE = {
    ResolutionState.UNKNOWN_DESIGNATOR: FindingCode.UNKNOWN_DESIGNATOR,
    ResolutionState.UNKNOWN_PART: FindingCode.UNKNOWN_PART,
    ResolutionState.UNKNOWN_PIN: FindingCode.UNKNOWN_PIN,
}


class UnresolvedReferences:
    """An error per reference, per net, that no longer names a pin: its designator is off the
    BOM, its part out of the catalog, or its pin off the pinout (requirements 2.1 to 2.3). A
    reference unresolved in two nets is two findings, since each net needs fixing."""

    code: ClassVar[FindingCode] = FindingCode.UNKNOWN_PIN

    def check(self, facts: WiringFacts) -> Iterable[Finding]:
        for net in facts.netlist.nets:
            for reference in net.content.pins:
                resolution = facts.resolution(reference)
                code = _BY_STATE.get(resolution.state)
                if code is not None:
                    yield Finding(
                        code, Severity.ERROR, (net.id,), (reference,), part=resolution.part
                    )


class PartsWithoutPinout:
    """One warning per part with no pinout that the netlist wires, naming its designators:
    its pins are taken by number and not checked (owner, 2026-09-29; requirement 2.4)."""

    code: ClassVar[FindingCode] = FindingCode.NO_PINOUT

    def check(self, facts: WiringFacts) -> Iterable[Finding]:
        parts: dict[PartId, PartFacts] = {}
        references: dict[PartId, set[PinReference]] = {}
        nets: dict[PartId, list[NetId]] = {}
        for net in facts.netlist.nets:
            for reference in net.content.pins:
                resolution = facts.resolution(reference)
                if resolution.state is not ResolutionState.UNCHECKED or resolution.part is None:
                    continue
                part_id = resolution.part.part_id
                parts[part_id] = resolution.part
                references.setdefault(part_id, set()).add(reference)
                if net.id not in nets.setdefault(part_id, []):
                    nets[part_id].append(net.id)
        for part_id, part in parts.items():
            held = tuple(sorted(references[part_id], key=PinReference.sort_key))
            yield Finding(
                FindingCode.NO_PINOUT,
                Severity.WARNING,
                tuple(nets[part_id]),
                held,
                part=part,
                designators=Designators.of({reference.designator for reference in held}),
            )


class PinReused:
    """An error per reference sitting in two or more nets, naming them all: one pin is one node,
    so two nets on it are one net or a typo (requirement 3). References compare as stored,
    whatever they resolve to, so an unchecked `R1.1` in two nets is found too."""

    code: ClassVar[FindingCode] = FindingCode.PIN_REUSED

    def check(self, facts: WiringFacts) -> Iterable[Finding]:
        holders: dict[PinReference, list[NetId]] = {}
        for net in facts.netlist.nets:
            for reference in net.content.pins:
                holders.setdefault(reference, []).append(net.id)
        for reference, net_ids in holders.items():
            if len(net_ids) > 1:
                yield Finding(FindingCode.PIN_REUSED, Severity.ERROR, tuple(net_ids), (reference,))


class VoltageMismatch:
    """An error per net whose resolved pins with a level don't all share it, grouped by level:
    a 5 V pin on a 3.3 V pin's net (requirement 4). Levels compare exactly, so 3V3 and 3.30
    are one; a pin without a level, unchecked or unresolved, is left out."""

    code: ClassVar[FindingCode] = FindingCode.VOLTAGE_MISMATCH

    def check(self, facts: WiringFacts) -> Iterable[Finding]:
        for net in facts.netlist.nets:
            levels: dict[Decimal, list[PinReference]] = {}
            for reference in net.content.pins:
                pin = facts.resolution(reference).pin
                if pin is not None and pin.voltage is not None:
                    levels.setdefault(pin.voltage.normalize(), []).append(reference)
            if len(levels) < _TWO:
                continue
            groups = tuple(
                VoltageGroup(voltage, tuple(levels[voltage])) for voltage in sorted(levels)
            )
            named = sorted(
                (reference for group in groups for reference in group.references),
                key=PinReference.sort_key,
            )
            yield Finding(
                FindingCode.VOLTAGE_MISMATCH,
                Severity.ERROR,
                (net.id,),
                tuple(named),
                levels=groups,
            )


# Two levels make a mismatch, and two references a connection.
_TWO = 2

# What can supply a net's signal (decision 6). An unchecked reference counts too: a resistor to
# 3V3 is how a pull-up drives an input, and its part has no pinout to say otherwise.
DRIVES = frozenset(
    {PinType.OUTPUT, PinType.IO, PinType.POWER, PinType.GROUND, PinType.ANALOG, PinType.OTHER}
)


class InputOnlyUndriven:
    """An error per net whose only pins that could supply its signal are input-only ones, so
    nothing drives it: GPIO34 wired only to a sensor's CSB (owner, 2026-09-29; requirement 5).
    A net of one reference is a wire still being made, and says nothing."""

    code: ClassVar[FindingCode] = FindingCode.INPUT_ONLY_UNDRIVEN

    def check(self, facts: WiringFacts) -> Iterable[Finding]:
        for net in facts.netlist.nets:
            if len(net.content.pins) < _TWO:
                continue
            resolutions = [facts.resolution(reference) for reference in net.content.pins]
            if any(_drives(resolution) for resolution in resolutions):
                continue
            inputs = tuple(r.reference for r in resolutions if _input_only(r))
            if inputs:
                yield Finding(FindingCode.INPUT_ONLY_UNDRIVEN, Severity.ERROR, (net.id,), inputs)


def _drives(resolution: Resolution) -> bool:
    if resolution.state is ResolutionState.UNCHECKED:
        return True
    return resolution.pin is not None and resolution.pin.type in DRIVES


def _input_only(resolution: Resolution) -> bool:
    return resolution.pin is not None and resolution.pin.type is PinType.INPUT


RULES: tuple[WiringRule, ...] = (
    UnresolvedReferences(),
    PinReused(),
    VoltageMismatch(),
    InputOnlyUndriven(),
    PartsWithoutPinout(),
)

_SEVERITY_ORDER = {Severity.ERROR: 0, Severity.WARNING: 1}


def check_wiring(facts: WiringFacts, rules: Sequence[WiringRule] = RULES) -> tuple[Finding, ...]:
    """Every rule's findings: errors first, then by rule, then by the first net named in the
    netlist's order, then by the first reference (decision 5, requirement 1.3)."""
    position = {net.id: index for index, net in enumerate(facts.netlist.nets)}
    last = len(position)

    def first_net(finding: Finding) -> int:
        return min((position.get(net_id, last) for net_id in finding.net_ids), default=last)

    ranked = [
        ((_SEVERITY_ORDER[finding.severity], rank, first_net(finding)), finding)
        for rank, rule in enumerate(rules)
        for finding in rule.check(facts)
    ]
    # Every finding names at least one reference, so the first of them breaks the last tie.
    ranked.sort(key=lambda entry: (entry[0], entry[1].references[0].sort_key()))
    return tuple(finding for _, finding in ranked)
