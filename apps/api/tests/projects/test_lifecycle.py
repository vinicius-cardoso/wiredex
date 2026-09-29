from datetime import UTC, datetime, timedelta
from uuid import uuid7

import pytest
from hypothesis import given
from hypothesis import strategies as st

from wiredex.projects.domain import lifecycle
from wiredex.projects.domain.errors import ProjectsError
from wiredex.projects.domain.lifecycle import (
    LIFECYCLE,
    LifecycleRefusal,
    Transition,
    TransitionNotAllowedError,
    step_for,
    transitions_from,
)
from wiredex.projects.domain.project import Project, ProjectDetails
from wiredex.projects.domain.revision import Revision, RevisionDetails
from wiredex.projects.domain.shortage import ShortageReport, ShortageSummary
from wiredex.projects.domain.values import (
    ProjectId,
    ProjectName,
    RevisionId,
    RevisionLabel,
    RevisionStatus,
    Summary,
    UnitId,
    WorkspaceId,
)

NOW = datetime(2026, 9, 28, 10, 0, tzinfo=UTC)
LATER = NOW + timedelta(days=1)
BENCH = WorkspaceId(uuid7())

# The four rows the table has, as (source, transition, target), so the test states them once
# and independently of LIFECYCLE's own tuple.
ROWS = {
    (RevisionStatus.DRAFT, Transition.RESERVE): RevisionStatus.RESERVED,
    (RevisionStatus.RESERVED, Transition.CANCEL): RevisionStatus.DRAFT,
    (RevisionStatus.RESERVED, Transition.BUILD): RevisionStatus.BUILT,
    (RevisionStatus.BUILT, Transition.DISMANTLE): RevisionStatus.DISMANTLED,
}


def a_revision(status: RevisionStatus = RevisionStatus.DRAFT) -> Revision:
    project = Project.start(
        ProjectId(uuid7()), BENCH, ProjectDetails(ProjectName("Weather station")), NOW
    )
    details = RevisionDetails(RevisionLabel("A"), Summary("breadboard"))
    revision = Revision.draft(RevisionId(uuid7()), project, details, NOW)
    revision.status = status
    return revision


# --- Property 1 ------------------------------------------------------------------------------


@given(status=st.sampled_from(list(RevisionStatus)), transition=st.sampled_from(list(Transition)))
def test_property_1_the_lifecycle_follows_its_table(
    status: RevisionStatus, transition: Transition
) -> None:
    """Property 1: the lifecycle follows its table.

    For any status and any transition, `Revision.ensure_allows` accepts the transition exactly
    when `LIFECYCLE` has a row leaving that status by it, and `move` then sets the row's target
    and stamps `updated_at`; for every other pair both raise `TransitionNotAllowedError` naming
    the status and the transition, and leave the revision as it was.

    **Validates: Requirements 1.1, 1.2, 1.6**
    """
    target = ROWS.get((status, transition))

    allows = a_revision(status)
    moves = a_revision(status)
    if target is None:
        for revision, act in ((allows, revision_allows), (moves, revision_move)):
            with pytest.raises(TransitionNotAllowedError) as caught:
                act(revision, transition)
            assert caught.value.transition is transition
            assert caught.value.status is status
            assert str(status) in str(caught.value)
            assert str(transition) in str(caught.value)
            # Refused: the revision is untouched.
            assert revision.status is status
            assert revision.updated_at == NOW
    else:
        allows.ensure_allows(transition)  # accepts, changes nothing
        assert allows.status is status
        assert allows.updated_at == NOW

        moves.move(transition, LATER)
        assert moves.status is target
        assert moves.updated_at == LATER


def revision_allows(revision: Revision, transition: Transition) -> None:
    revision.ensure_allows(transition)


def revision_move(revision: Revision, transition: Transition) -> None:
    revision.move(transition, LATER)


@given(start=st.lists(st.sampled_from(list(Transition)), max_size=8))
def test_any_walk_from_draft_stays_on_the_table(start: list[Transition]) -> None:
    # Any sequence of transitions from a draft walks only the table's rows: each accepted move
    # lands on a status the table names, and once dismantled none is accepted.
    revision = a_revision(RevisionStatus.DRAFT)
    for transition in start:
        before = revision.status
        expected = ROWS.get((before, transition))
        if expected is None:
            with pytest.raises(TransitionNotAllowedError):
                revision.move(transition, LATER)
            assert revision.status is before
        else:
            revision.move(transition, LATER)
            assert revision.status is expected
    if revision.status is RevisionStatus.DISMANTLED:
        for transition in Transition:
            with pytest.raises(TransitionNotAllowedError):
                revision.move(transition, LATER)


# --- The table itself ------------------------------------------------------------------------


def test_the_table_has_exactly_the_four_rows() -> None:
    assert {(step.source, step.transition): step.target for step in LIFECYCLE} == ROWS


@pytest.mark.parametrize(("source", "transition"), list(ROWS))
def test_step_for_finds_each_row(source: RevisionStatus, transition: Transition) -> None:
    step = step_for(source, transition)
    assert step is not None
    assert step.target is ROWS[(source, transition)]


def test_step_for_answers_none_off_the_table() -> None:
    assert step_for(RevisionStatus.DRAFT, Transition.BUILD) is None
    assert step_for(RevisionStatus.DISMANTLED, Transition.RESERVE) is None


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (RevisionStatus.DRAFT, (Transition.RESERVE,)),
        (RevisionStatus.RESERVED, (Transition.CANCEL, Transition.BUILD)),
        (RevisionStatus.BUILT, (Transition.DISMANTLE,)),
        (RevisionStatus.DISMANTLED, ()),
    ],
)
def test_transitions_from_lists_the_rows_in_order(
    status: RevisionStatus, expected: tuple[Transition, ...]
) -> None:
    assert transitions_from(status) == expected


# --- holds_stock and deletable ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "holds", "deletable"),
    [
        (RevisionStatus.DRAFT, False, True),
        (RevisionStatus.RESERVED, True, False),
        (RevisionStatus.BUILT, True, False),
        (RevisionStatus.DISMANTLED, False, True),
    ],
)
def test_holds_stock_and_deletable(status: RevisionStatus, holds: bool, deletable: bool) -> None:
    assert status.holds_stock is holds
    assert status.deletable is deletable


@given(status=st.sampled_from(list(RevisionStatus)))
def test_deletable_is_the_opposite_of_holds_stock(status: RevisionStatus) -> None:
    # Over the four statuses the two are opposites, but both are stated, so a status added
    # later has to answer both.
    assert status.deletable is not status.holds_stock


# --- The ten refusal codes -------------------------------------------------------------------

TEN_CODES = {
    "transition_not_allowed",
    "empty_bom",
    "short",
    "unknown_unit",
    "repeated_unit",
    "unit_not_needed",
    "too_many_units",
    "unit_not_in_stock",
    "unknown_location",
    "stock_changed",
}


def _refusal_leaves() -> list[type[LifecycleRefusal]]:
    return [
        leaf
        for leaf in vars(lifecycle).values()
        if isinstance(leaf, type)
        and issubclass(leaf, LifecycleRefusal)
        and hasattr(leaf, "code")
        and not getattr(leaf, "__name__", "").startswith("_")
        and leaf is not LifecycleRefusal
    ]


def test_the_ten_refusal_codes_each_belong_to_one_leaf() -> None:
    # The web has one sentence per code, so every code is raised by exactly one leaf and none
    # is left over.
    assert sorted(leaf.code for leaf in _refusal_leaves()) == sorted(TEN_CODES)


def test_every_refusal_is_a_projects_error() -> None:
    # The router maps LifecycleRefusal by its code; every leaf is a ProjectsError (a ValueError).
    for leaf in _refusal_leaves():
        assert issubclass(leaf, ProjectsError)


def test_transition_not_allowed_carries_the_status_and_transition() -> None:
    refused = TransitionNotAllowedError("nope", Transition.BUILD, RevisionStatus.DRAFT)
    assert refused.code == "transition_not_allowed"
    assert refused.transition is Transition.BUILD
    assert refused.status is RevisionStatus.DRAFT


def test_a_named_unit_refusal_carries_the_unit() -> None:
    unit_id = UnitId(uuid7())
    refused = lifecycle.UnknownUnitError("no such unit", Transition.RESERVE, unit_id)
    assert refused.code == "unknown_unit"
    assert refused.unit_id == unit_id
    assert refused.unit_code is None

    known = lifecycle.TooManyUnitsError(
        "too many", Transition.RESERVE, unit_id, unit_code="WX-U-0004"
    )
    assert known.unit_code == "WX-U-0004"


def test_a_short_refusal_carries_its_report() -> None:
    report = ShortageReport(parts=(), summary=ShortageSummary(0, 0, 0, 0, 0, 0))
    refused = lifecycle.ShortError("short", Transition.RESERVE, report)
    assert refused.code == "short"
    assert refused.report is report
