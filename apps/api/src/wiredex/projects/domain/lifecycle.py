"""The revision lifecycle as a table (decision 11).

ADR 0003's state machine, `Draft → Reserved → Built → Dismantled` with `Reserved → Draft` on
cancel, is docs/architecture.md §5's State pattern in its data form: four states whose only
behaviour is which moves they allow are one table, `LIFECYCLE`, that a property can enumerate,
not four classes each answering the one question. What differs between the transitions, the
stock effect, needs the ports and lives in the use cases either way.

A transition's refusals share one base, `LifecycleRefusal`, so projects' router answers each in
one shape and the web translates its `code` (decision 14). They live here because
`Revision.ensure_allows` and the reservation checks raise them.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, ClassVar

from wiredex.projects.domain.errors import ProjectsError
from wiredex.projects.domain.values import RevisionStatus, UnitId

if TYPE_CHECKING:
    # Imported only for the type of ShortError.report: shortage -> bom -> revision -> lifecycle
    # is a cycle at import time, and ShortError needs nothing of it to run.
    from wiredex.projects.domain.shortage import ShortageReport


class Transition(StrEnum):
    """The four moves between statuses (requirement 1.1)."""

    RESERVE = "reserve"
    CANCEL = "cancel"
    BUILD = "build"
    DISMANTLE = "dismantle"


@dataclass(frozen=True, slots=True)
class Step:
    """One row of the lifecycle: the transition that leaves `source` for `target`."""

    source: RevisionStatus
    transition: Transition
    target: RevisionStatus


LIFECYCLE: tuple[Step, ...] = (
    Step(RevisionStatus.DRAFT, Transition.RESERVE, RevisionStatus.RESERVED),
    Step(RevisionStatus.RESERVED, Transition.CANCEL, RevisionStatus.DRAFT),
    Step(RevisionStatus.RESERVED, Transition.BUILD, RevisionStatus.BUILT),
    Step(RevisionStatus.BUILT, Transition.DISMANTLE, RevisionStatus.DISMANTLED),
)


def step_for(status: RevisionStatus, transition: Transition) -> Step | None:
    """The row leaving `status` by `transition`, or None when the table has none (1.1)."""
    for step in LIFECYCLE:
        if step.source is status and step.transition is transition:
            return step
    return None


def transitions_from(status: RevisionStatus) -> tuple[Transition, ...]:
    """The transitions the table allows from `status`, in its order (10.1, 13.1)."""
    return tuple(step.transition for step in LIFECYCLE if step.source is status)


class LifecycleRefusal(ProjectsError):  # noqa: N818  the design names it a refusal, not an error
    """A transition refused before it wrote anything.

    `code` is what the web translates into the reader's language (requirement 13.13); the
    English message names what broke, for API clients and logs. Every subclass carries the
    transition the request asked for, so the refusal says which move was refused.
    """

    code: ClassVar[str]

    def __init__(self, message: str, transition: Transition) -> None:
        super().__init__(message)
        self.transition = transition


class TransitionNotAllowedError(LifecycleRefusal):
    """The status has no row leaving it by the transition (requirements 1.2, 1.5). It carries
    the status so the refusal names both what was asked and where the revision stands."""

    code = "transition_not_allowed"

    def __init__(self, message: str, transition: Transition, status: RevisionStatus) -> None:
        super().__init__(message, transition)
        self.status = status


class EmptyBomError(LifecycleRefusal):
    """A reserve of a revision whose BOM has no lines (requirement 2.3)."""

    code = "empty_bom"


class ShortError(LifecycleRefusal):
    """A reserve where a part is short or unknown (requirements 2.1, 2.2, 2.8). It carries the
    report computed on the locked stock, so the refusal names each short and unknown part."""

    code = "short"

    def __init__(self, message: str, transition: Transition, report: ShortageReport) -> None:
        super().__init__(message, transition)
        self.report = report


class _NamedUnitError(LifecycleRefusal):
    """A reserve refused for one of the units the owner named. It carries the unit's id and,
    when the workspace holds the unit, its code (requirements 3.4, 3.5)."""

    def __init__(
        self,
        message: str,
        transition: Transition,
        unit_id: UnitId,
        unit_code: str | None = None,
    ) -> None:
        super().__init__(message, transition)
        self.unit_id = unit_id
        self.unit_code = unit_code


class UnknownUnitError(_NamedUnitError):
    """A named unit the workspace doesn't hold, another workspace's included, which row-level
    security hides the same way (requirements 3.4, 11.2)."""

    code = "unknown_unit"


class RepeatedUnitError(_NamedUnitError):
    """A unit the reserve names twice (requirement 3.4)."""

    code = "repeated_unit"


class UnitNotNeededError(_NamedUnitError):
    """A named unit of a part with no stocked need, a consumable's included (2.7, 3.4)."""

    code = "unit_not_needed"


class TooManyUnitsError(_NamedUnitError):
    """More named units of a part than its need (requirement 3.4)."""

    code = "too_many_units"


class UnitNotInStockError(_NamedUnitError):
    """A named unit that isn't in stock, or past what its lot's available stock covers (3.5)."""

    code = "unit_not_in_stock"


class UnknownLocationError(LifecycleRefusal):
    """A dismantle naming a location the workspace doesn't hold (requirements 6.1, 11.2)."""

    code = "unknown_location"


class StockChangedError(LifecycleRefusal):
    """The recount after the balance lock found an in-stock unit the unit lock missed: a
    receipt committed between the two locks (decision 12). Pressing the button again clears
    it, so nothing retries it."""

    code = "stock_changed"
