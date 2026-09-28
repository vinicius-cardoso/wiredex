"""The project use cases over the in-memory projects fakes.

The fakes write straight into their stores and count commits and reads, so a refused change is
one that left the stores as they were and committed nothing, and a page's cost is a number.
"""

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from uuid import uuid7

import anyio
import pytest
from hypothesis import given
from hypothesis import strategies as st

from support.projects import BENCH, NOW, World
from wiredex.projects.application.ports import TagCount
from wiredex.projects.domain.errors import (
    DuplicateProjectNameError,
    ProjectNotFoundError,
    RevisionInUseError,
)
from wiredex.projects.domain.filter import ProjectFilter
from wiredex.projects.domain.project import ProjectDetails
from wiredex.projects.domain.values import (
    Description,
    ProjectId,
    ProjectName,
    RevisionLabel,
    RevisionStatus,
    Tag,
    Tags,
)

pytestmark = pytest.mark.anyio


def details(
    name: str = "Weather station", description: str | None = None, tags: tuple[str, ...] = ()
) -> ProjectDetails:
    return ProjectDetails(
        ProjectName(name),
        None if description is None else Description(description),
        Tags.of(tags),
    )


class TestCreate:
    async def test_writes_the_project_and_revision_a_in_one_commit(self) -> None:
        # Requirement 1.1.
        world = World()

        view = await world.create_project(BENCH, details(tags=("ESP32", "i2c")))

        assert world.work.commits == 1
        assert world.work.opened_for == [BENCH]
        assert world.work.projects.saved == {view.project.id: view.project}
        assert view.project.tags == Tags.of(["esp32", "i2c"])
        [first] = world.work.revisions.saved.values()
        assert view.revisions.items == (first,)
        assert first.project_id == view.project.id
        assert first.workspace_id == BENCH
        assert first.label == RevisionLabel("A")
        assert first.status is RevisionStatus.DRAFT
        assert first.created_at == view.project.created_at == NOW

    async def test_refuses_a_name_another_project_holds_in_another_case(self) -> None:
        # Requirement 1.3: the message names the project that holds it.
        world = World()
        world.hold_project("Weather station")

        with pytest.raises(DuplicateProjectNameError, match="a project named Weather station"):
            await world.create_project(BENCH, details("WEATHER  station"))

        assert world.work.commits == 0
        assert len(world.work.projects.saved) == 1
        assert len(world.work.revisions.saved) == 1


class TestUpdate:
    async def test_replaces_the_details(self) -> None:
        # Requirement 1.5: whole, so tags left out of the edit are gone.
        world = World()
        project = world.hold_project("Weather station", tags=("esp32", "i2c"))
        world.clock.advance(timedelta(minutes=5))

        view = await world.update_project(
            BENCH, project.id, details("Weather station v2", "Logs every minute.", ("lora",))
        )

        assert view.project is project
        assert project.details == details("Weather station v2", "Logs every minute.", ("lora",))
        assert project.updated_at == NOW + timedelta(minutes=5)
        assert [revision.label.value for revision in view.revisions.items] == ["A"]
        assert world.work.commits == 1

    async def test_an_edit_that_changes_nothing_commits_nothing(self) -> None:
        world = World()
        project = world.hold_project("Weather station", tags=("esp32",))
        world.clock.advance(timedelta(minutes=5))

        await world.update_project(BENCH, project.id, details(tags=("ESP32",)))

        assert world.work.commits == 0
        assert project.updated_at == NOW

    async def test_refuses_a_name_another_project_holds_in_another_case(self) -> None:
        world = World()
        world.hold_project("Weather station")
        greenhouse = world.hold_project("Greenhouse controller")

        with pytest.raises(DuplicateProjectNameError, match="a project named Weather station"):
            await world.update_project(BENCH, greenhouse.id, details("weather station"))

        assert greenhouse.name == ProjectName("Greenhouse controller")
        assert world.work.commits == 0

    async def test_keeps_its_own_name_in_another_case(self) -> None:
        world = World()
        project = world.hold_project("Weather station")

        await world.update_project(BENCH, project.id, details("Weather Station"))

        assert project.name == ProjectName("Weather Station")
        assert world.work.commits == 1


class TestDelete:
    async def test_takes_its_revisions_with_it(self) -> None:
        # Requirement 1.7, under the project's lock.
        world = World()
        project = world.hold_project("Weather station")
        world.hold_revision(project, "B", minutes=1)
        other = world.hold_project("Greenhouse controller")

        await world.delete_project(BENCH, project.id)

        assert world.work.projects.saved == {other.id: other}
        assert {r.project_id for r in world.work.revisions.saved.values()} == {other.id}
        assert world.work.projects.locks == [project.id]
        assert world.work.commits == 1

    async def test_is_refused_while_a_revision_isnt_a_draft(self) -> None:
        # Requirement 1.8, with a built revision placed in the fakes: nothing moves a revision
        # out of draft before 10-build-lifecycle.
        world = World()
        project = world.hold_project("Weather station")
        world.hold_revision(project, "B", status=RevisionStatus.BUILT, minutes=1)

        with pytest.raises(RevisionInUseError, match="revision B is built"):
            await world.delete_project(BENCH, project.id)

        assert project.id in world.work.projects.saved
        assert len(world.work.revisions.saved) == 2
        assert world.work.commits == 0


async def test_get_answers_the_revisions_the_latest_and_the_next_label() -> None:
    # Requirement 1.6: B was created after A, so B is the latest and C comes next.
    world = World()
    project = world.hold_project("Weather station")
    second = world.hold_revision(project, "B", minutes=1)

    view = await world.get_project(BENCH, project.id)

    assert view.project is project
    assert [revision.label.value for revision in view.revisions.items] == ["A", "B"]
    assert view.revisions.latest is second
    assert view.revisions.suggested_label() == RevisionLabel("C")
    assert world.work.commits == 0


async def test_the_tag_counts_are_alphabetical_with_their_projects() -> None:
    # Requirement 2.6.
    world = World()
    world.hold_project("Weather station", tags=("i2c", "esp32"))
    world.hold_project("Greenhouse controller", tags=("esp32", "relay"))
    world.hold_project("Bench supply")

    assert await world.list_project_tags(BENCH) == [
        TagCount(Tag("esp32"), 2),
        TagCount(Tag("i2c"), 1),
        TagCount(Tag("relay"), 1),
    ]


def _get(world: World, project_id: ProjectId) -> Awaitable[object]:
    return world.get_project(BENCH, project_id)


def _update(world: World, project_id: ProjectId) -> Awaitable[object]:
    return world.update_project(BENCH, project_id, details())


def _delete(world: World, project_id: ProjectId) -> Awaitable[object]:
    return world.delete_project(BENCH, project_id)


@pytest.mark.parametrize("action", [_get, _update, _delete], ids=["get", "update", "delete"])
async def test_a_project_not_in_the_workspace_is_not_found(
    action: Callable[[World, ProjectId], Awaitable[object]],
) -> None:
    # Requirement 1.9.
    world = World()
    world.hold_project("Weather station")

    with pytest.raises(ProjectNotFoundError, match="that project doesn't exist"):
        await action(world, ProjectId(uuid7()))

    assert world.work.commits == 0


class TestList:
    async def test_is_empty_when_nothing_matches(self) -> None:
        # Requirement 3.5.
        world = World()
        world.hold_project("Weather station", tags=("esp32",))

        assert await world.list_projects(BENCH, ProjectFilter("greenhouse")) == []
        assert await world.list_projects(BENCH, ProjectFilter(tags=Tags.of(["relay"]))) == []

    async def test_a_row_carries_the_latest_revision_and_the_count(self) -> None:
        # Requirement 3.1, and 3.2: editing B at minute 9 puts the project above one whose own
        # details changed at minute 5.
        world = World()
        weather = world.hold_project("Weather station")
        second = world.hold_revision(weather, "B", minutes=1)
        second.updated_at = NOW + timedelta(minutes=9)
        greenhouse = world.hold_project("Greenhouse controller", minutes=5)

        rows = await world.list_projects(BENCH, ProjectFilter())

        assert [row.project for row in rows] == [weather, greenhouse]
        assert rows[0].latest is second
        assert rows[0].revision_count == 2
        assert rows[0].last_activity == NOW + timedelta(minutes=9)
        assert rows[1].revision_count == 1

    async def test_leaves_out_a_project_whose_revisions_went_between_its_reads(self) -> None:
        # Only deleting a project takes its last revision, so such a project is gone too.
        world = World()
        world.hold_project("Weather station", revision=None)

        assert await world.list_projects(BENCH, ProjectFilter()) == []


@pytest.mark.parametrize("size", [1, 25])
async def test_a_page_and_a_list_cost_two_reads_whatever_their_size(size: int) -> None:
    # Requirement 11.3: the project, then its revisions; the projects, then all their revisions.
    world = World()
    projects = [world.hold_project(f"Project {number}") for number in range(size)]
    for number in range(size):
        world.hold_revision(projects[0], f"R{number}", minutes=number + 1)

    await world.get_project(BENCH, projects[0].id)
    assert world.work.reads == 2

    rows = await world.list_projects(BENCH, ProjectFilter())
    assert len(rows) == size
    assert world.work.reads == 4


# --- Property 7: the list shows every match once, freshest first -----------------------

_TAG_POOL = ("esp32", "i2c", "outdoor", "relay")
# A small alphabet, so texts often fall inside names, and % and _ have to match themselves.
_NAMES = st.text(alphabet="aAbB%_", min_size=1, max_size=5)
_TEXTS = st.none() | st.text(alphabet="aAbB%_ ", max_size=3)
_TAGS = st.lists(st.sampled_from(_TAG_POOL), max_size=3)
# (created, then updated so many minutes later) for each revision; a narrow clock makes ties.
_REVISIONS = st.lists(st.tuples(st.integers(0, 4), st.integers(0, 3)), min_size=1, max_size=3)
_PROJECTS = st.lists(
    st.tuples(_NAMES, _TAGS, st.integers(0, 6), _REVISIONS), unique_by=lambda p: p[0].lower()
)


@given(
    projects=_PROJECTS,
    text=_TEXTS,
    wanted_tags=st.lists(st.sampled_from(_TAG_POOL), max_size=2),
)
def test_the_list_shows_every_match_once_freshest_first(
    projects: list[tuple[str, list[str], int, list[tuple[int, int]]]],
    text: str | None,
    wanted_tags: list[str],
) -> None:
    """Property 7: the list shows every match once, freshest first.

    For any projects with any revisions and update dates, and any filter of a text and tags,
    ListProjects answers exactly the projects whose name holds the text ignoring case and whose
    tags include every wanted tag, each once, with its latest revision and its number of
    revisions, ordered by last activity (the later of the project's own date and its
    revisions' dates) newest first, ties broken by id.

    **Validates: Requirements 3.1, 3.2, 3.4**
    """

    async def scenario() -> None:
        world = World()
        for name, tags, updated, revisions in projects:
            project = world.hold_project(name, tags=tags, minutes=updated, revision=None)
            for label, (created, later) in enumerate(revisions):
                revision = world.hold_revision(project, f"R{label}", minutes=created)
                revision.updated_at += timedelta(minutes=later)
        wanted = ProjectFilter(text, Tags.of(wanted_tags))

        rows = await world.list_projects(BENCH, wanted)

        needle = (text or "").strip().lower()
        expected = [
            project
            for project in world.work.projects.saved.values()
            if needle in project.name.value.lower()
            and set(Tags.of(wanted_tags).values) <= set(project.tags.values)
        ]

        def activity(project_id: ProjectId) -> tuple[datetime, ProjectId]:
            dates = [
                r.updated_at
                for r in world.work.revisions.saved.values()
                if r.project_id == project_id
            ]
            return (max([world.work.projects.saved[project_id].updated_at, *dates]), project_id)

        expected.sort(key=lambda project: activity(project.id), reverse=True)
        assert [row.project for row in rows] == expected
        for row in rows:
            own = [r for r in world.work.revisions.saved.values() if r.project_id == row.project.id]
            assert row.revision_count == len(own)
            assert row.latest is max(own, key=lambda r: (r.created_at, r.id))
            assert (row.last_activity, row.project.id) == activity(row.project.id)

    anyio.run(scenario)
