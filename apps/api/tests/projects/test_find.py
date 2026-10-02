"""Finding projects by typed text over the in-memory projects (19-command-palette).

The SQL's own share, one statement, the wildcards as typed and the other bench left out, is
`tests/integration/test_find_reads.py`'s.
"""

import pytest

from support.projects import BENCH, NOW, World
from wiredex.projects.application.find import FindProjects
from wiredex.projects.domain.project import Project

pytestmark = pytest.mark.anyio


def names(found: list[Project]) -> list[str]:
    return [str(project.name) for project in found]


async def test_matches_the_name_case_aside_the_ones_starting_with_it_first() -> None:
    # Requirements 1.1 and 1.3.
    world = World()
    for name in ("Old weather station", "weather vane", "Weather station", "Robot"):
        world.hold_project(name)
    find = FindProjects(world.work.for_workspace)

    found = await find(BENCH, "WEATHER", 10)

    assert names(found) == ["Weather station", "weather vane", "Old weather station"]
    assert world.work.opened_for == [BENCH]


async def test_answers_at_most_the_limit() -> None:
    world = World()
    for index in range(4):
        world.hold_project(f"Station {index}")
    find = FindProjects(world.work.for_workspace)

    assert names(await find(BENCH, "station", 2)) == ["Station 0", "Station 1"]


async def test_a_blank_text_finds_nothing_and_opens_nothing() -> None:
    world = World()
    world.hold_project("Weather station")
    find = FindProjects(world.work.for_workspace)

    assert await find(BENCH, "  ", 10) == []
    assert world.work.opened_for == []


async def test_a_project_in_the_trash_is_never_found() -> None:
    # Requirement 2.1 (16-soft-delete-and-trash, decision 2).
    world = World()
    world.hold_project("Weather station")
    world.hold_project("Weather vane").move_to_trash(NOW)
    find = FindProjects(world.work.for_workspace)

    assert names(await find(BENCH, "weather", 10)) == ["Weather station"]
