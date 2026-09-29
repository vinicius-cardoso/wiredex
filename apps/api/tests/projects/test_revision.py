from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid7

import pytest

from wiredex.projects.domain.errors import RevisionContentLockedError, RevisionHoldsStockError
from wiredex.projects.domain.project import Project, ProjectDetails
from wiredex.projects.domain.revision import Revision, RevisionDetails
from wiredex.projects.domain.values import (
    Notes,
    ProjectId,
    ProjectName,
    RevisionId,
    RevisionLabel,
    RevisionStatus,
    Summary,
    WorkspaceId,
)

NOW = datetime(2026, 9, 27, 10, 0, tzinfo=UTC)
LATER = NOW + timedelta(days=1)
BENCH = WorkspaceId(uuid7())

BREADBOARD = RevisionDetails(RevisionLabel("A"), Summary("breadboard"), Notes("First try."))
PERFBOARD = RevisionDetails(RevisionLabel("B"), Summary("perfboard"))


def a_project() -> Project:
    return Project.start(
        ProjectId(uuid7()), BENCH, ProjectDetails(ProjectName("Weather station")), NOW
    )


def a_revision(status: RevisionStatus = RevisionStatus.DRAFT) -> Revision:
    revision = Revision.draft(RevisionId(uuid7()), a_project(), BREADBOARD, NOW)
    # Only 10-build-lifecycle moves a status; until then the tests place one.
    revision.status = status
    return revision


def test_a_draft_takes_its_projects_workspace_and_id() -> None:
    project = a_project()

    revision = Revision.draft(RevisionId(uuid7()), project, BREADBOARD, NOW)

    assert revision.workspace_id == project.workspace_id
    assert revision.project_id == project.id
    assert revision.details == BREADBOARD
    assert revision.status is RevisionStatus.DRAFT
    assert revision.forked_from is None
    assert revision.created_at == revision.updated_at == NOW


@pytest.mark.parametrize("status", list(RevisionStatus))
def test_a_fork_of_any_status_is_a_draft_of_the_sources_project(status: RevisionStatus) -> None:
    # Requirement 6.5: the perfboard starts from the breadboard that was built.
    source = a_revision(status)

    fork = Revision.fork_of(source, RevisionId(uuid7()), PERFBOARD, LATER)

    assert fork.workspace_id == source.workspace_id
    assert fork.project_id == source.project_id
    assert fork.forked_from == source.id
    assert fork.status is RevisionStatus.DRAFT
    # The summary and notes are the fork's own, not carried from the source.
    assert fork.details == PERFBOARD
    assert fork.created_at == fork.updated_at == LATER
    assert source.status is status


@pytest.mark.parametrize("status", list(RevisionStatus))
def test_a_revision_is_revised_in_any_status(status: RevisionStatus) -> None:
    revision = a_revision(status)
    edited = RevisionDetails(RevisionLabel("A1"), Summary("breadboard, rewired"))

    assert revision.revise(edited, LATER)
    assert revision.details == edited
    assert revision.notes is None
    assert revision.status is status
    assert revision.updated_at == LATER


def test_revising_with_the_same_details_changes_nothing() -> None:
    revision = a_revision()

    assert not revision.revise(replace(BREADBOARD, summary=Summary(" breadboard ")), LATER)
    assert revision.updated_at == NOW


@pytest.mark.parametrize("status", [RevisionStatus.DRAFT, RevisionStatus.DISMANTLED])
def test_a_revision_holding_no_stock_can_be_deleted(status: RevisionStatus) -> None:
    # A draft and a dismantled revision hold nothing, so both go (decision 7, widening 08).
    a_revision(status).ensure_deletable()


@pytest.mark.parametrize(
    ("status", "frees"),
    [
        (RevisionStatus.RESERVED, "cancel the reservation"),
        (RevisionStatus.BUILT, "dismantle the build"),
    ],
)
def test_a_revision_holding_stock_is_refused_saying_what_frees_it(
    status: RevisionStatus, frees: str
) -> None:
    # Requirement 9.1: the refusal says whether cancelling or dismantling comes first.
    with pytest.raises(RevisionHoldsStockError, match=f"revision A is {status}") as caught:
        a_revision(status).ensure_deletable()
    assert frees in str(caught.value)


def test_a_drafts_content_is_editable() -> None:
    a_revision().ensure_content_editable()


@pytest.mark.parametrize(
    "status", [RevisionStatus.RESERVED, RevisionStatus.BUILT, RevisionStatus.DISMANTLED]
)
def test_only_a_drafts_content_is_editable(status: RevisionStatus) -> None:
    # Decision 11: the BOM of a reserved, built or dismantled revision is that build's record.
    with pytest.raises(RevisionContentLockedError, match=f"revision A is {status}"):
        a_revision(status).ensure_content_editable()


def test_touch_moves_the_last_change_and_nothing_else() -> None:
    revision = a_revision()
    details = revision.details

    revision.touch(LATER)

    assert revision.updated_at == LATER
    assert revision.created_at == NOW
    assert revision.details == details
