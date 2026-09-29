"""What is wired to each pin of a part, across the workspace's projects (12-wiring-validation).

A use is one net of one revision that a pin of the part is on, through one BOM designator
holding it. `PinUsage.of` sorts the uses under the pins of the pinout, in its saved order; a
use whose number the pinout lacks, or every use of a part with no pinout, goes under *other
pins*, since a reference is stored as text and outlives the pin it named (decision 8). The uses
arrive already in requirement 7.4's order, and each group keeps it.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from wiredex.projects.domain.designators import Designator
from wiredex.projects.domain.netlist import NetName, WireColor
from wiredex.projects.domain.pins import PartPins, PinFacts, PinNumber
from wiredex.projects.domain.shortage import PartFacts
from wiredex.projects.domain.values import (
    NetId,
    ProjectId,
    ProjectName,
    RevisionId,
    RevisionLabel,
    RevisionStatus,
)


@dataclass(frozen=True, slots=True)
class PinUse:
    """One net of one revision that a pin of the part is on, through one designator."""

    project_id: ProjectId
    project_name: ProjectName
    revision_id: RevisionId
    revision_label: RevisionLabel
    status: RevisionStatus
    designator: Designator
    pin: PinNumber
    net_id: NetId
    net_name: NetName
    color: WireColor | None


@dataclass(frozen=True, slots=True)
class PinUsage:
    part: PartFacts
    pins: tuple[tuple[PinFacts, tuple[PinUse, ...]], ...]  # saved order; empty uses = free
    others: tuple[tuple[PinNumber, tuple[PinUse, ...]], ...]  # natural order

    @property
    def has_pinout(self) -> bool:
        return bool(self.pins)

    @classmethod
    def of(cls, part: PartFacts, pinout: PartPins | None, uses: Sequence[PinUse]) -> PinUsage:
        by_number: dict[PinNumber, list[PinUse]] = {}
        for use in uses:
            by_number.setdefault(use.pin, []).append(use)
        pins = pinout.pins if pinout is not None else ()
        held = {pin.number for pin in pins}
        others = sorted(
            (number for number in by_number if number not in held), key=PinNumber.sort_key
        )
        return cls(
            part,
            tuple((pin, tuple(by_number.get(pin.number, ()))) for pin in pins),
            tuple((number, tuple(by_number[number])) for number in others),
        )
