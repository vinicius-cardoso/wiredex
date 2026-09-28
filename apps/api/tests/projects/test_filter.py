from datetime import UTC, datetime
from uuid import uuid7

import pytest

from wiredex.projects.domain.filter import ProjectFilter
from wiredex.projects.domain.project import Project, ProjectDetails
from wiredex.projects.domain.values import ProjectId, ProjectName, Tags, WorkspaceId

NOW = datetime(2026, 9, 27, 10, 0, tzinfo=UTC)


def a_project(name: str = "Weather Station", tags: tuple[str, ...] = ("esp32", "i2c")) -> Project:
    details = ProjectDetails(ProjectName(name), tags=Tags.of(tags))
    return Project.start(ProjectId(uuid7()), WorkspaceId(uuid7()), details, NOW)


@pytest.mark.parametrize("text", ["weather", "STATION", "r St", "Weather Station"])
def test_the_text_is_found_in_the_name_ignoring_case(text: str) -> None:
    assert ProjectFilter(text).matches(a_project())


def test_a_name_without_the_text_is_left_out() -> None:
    assert not ProjectFilter("greenhouse").matches(a_project())


def test_every_wanted_tag_is_required() -> None:
    project = a_project()

    assert ProjectFilter(tags=Tags.of(["ESP32"])).matches(project)
    assert ProjectFilter(tags=Tags.of(["esp32", "i2c"])).matches(project)
    assert not ProjectFilter(tags=Tags.of(["esp32", "relay"])).matches(project)


def test_text_and_tags_must_both_hold() -> None:
    project = a_project()

    assert ProjectFilter("weather", Tags.of(["i2c"])).matches(project)
    assert not ProjectFilter("greenhouse", Tags.of(["i2c"])).matches(project)
    assert not ProjectFilter("weather", Tags.of(["relay"])).matches(project)


@pytest.mark.parametrize("text", [None, "", "   ", "\t\n"])
def test_a_blank_text_asks_for_nothing(text: str | None) -> None:
    wanted = ProjectFilter(text)

    assert wanted.text is None
    assert wanted.matches(a_project())
    assert wanted.matches(a_project("Greenhouse controller", ()))


def test_the_text_is_trimmed() -> None:
    assert ProjectFilter("  weather ").text == "weather"


def test_percent_and_underscore_are_plain_characters() -> None:
    # Requirement 3.3: the SQL escapes them, and the fake has to agree.
    assert not ProjectFilter("W%r").matches(a_project())
    assert not ProjectFilter("W_ather").matches(a_project())
    assert ProjectFilter("100%").matches(a_project("Dimmer at 100%"))
