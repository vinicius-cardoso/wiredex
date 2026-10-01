from datetime import UTC, datetime, timedelta
from uuid import uuid7

from wiredex.projects.domain.project import Project, ProjectDetails
from wiredex.projects.domain.values import (
    Description,
    ProjectId,
    ProjectName,
    Tags,
    WorkspaceId,
)

NOW = datetime(2026, 9, 27, 10, 0, tzinfo=UTC)
LATER = NOW + timedelta(hours=3)
BENCH = WorkspaceId(uuid7())

DETAILS = ProjectDetails(
    ProjectName("Weather station"),
    Description("A BME280 on an ESP32, logging every five minutes."),
    Tags.of(["esp32", "i2c"]),
)


def a_project(details: ProjectDetails = DETAILS) -> Project:
    return Project.start(ProjectId(uuid7()), BENCH, details, NOW)


def test_a_new_project_is_created_and_updated_at_the_same_instant() -> None:
    project = a_project()

    assert project.workspace_id == BENCH
    assert project.details == DETAILS
    assert project.created_at == project.updated_at == NOW


def test_a_project_needs_nothing_but_a_name() -> None:
    project = a_project(ProjectDetails(ProjectName("Greenhouse controller")))

    assert project.description is None
    assert project.tags == Tags.none()


def test_revising_a_project_replaces_its_details_and_stamps_when() -> None:
    project = a_project()
    edited = ProjectDetails(ProjectName("Weather station v2"), tags=Tags.of(["outdoor"]))

    assert project.revise(edited, LATER)
    assert project.details == edited
    # The details are replaced whole, so the description left out is cleared.
    assert project.description is None
    assert project.created_at == NOW
    assert project.updated_at == LATER


def test_revising_with_the_same_details_changes_nothing_and_keeps_the_stamp() -> None:
    # Requirement 1.5: the use case skips the commit on False, and a project whose date moved
    # would climb the list for an edit that did nothing.
    project = a_project()
    same = ProjectDetails(
        ProjectName(" Weather  station "),
        Description("A BME280 on an ESP32, logging every five minutes.\n"),
        Tags.of(["I2C", "ESP32"]),
    )

    assert not project.revise(same, LATER)
    assert project.updated_at == NOW


def test_touching_a_project_moves_only_its_date() -> None:
    project = a_project()

    project.touch(LATER)

    assert project.updated_at == LATER
    assert project.details == DETAILS


def test_a_project_moved_to_the_trash_keeps_its_details_and_its_date() -> None:
    project = a_project()
    project.move_to_trash(LATER)

    assert project.in_trash
    assert project.trashed_at == LATER
    assert project.details == DETAILS
    assert project.updated_at == NOW


def test_a_project_restored_from_the_trash_is_live_again_as_it_was() -> None:
    project = a_project()
    project.move_to_trash(LATER)

    project.restore_from_trash()

    assert not project.in_trash
    assert project.trashed_at is None
    assert project.updated_at == NOW
