"""Projects' share of the trash over the in-memory projects (16-soft-delete-and-trash).

Moving a project to the trash is `DeleteProject`, whose refusals `test_project_use_cases.py`
covers; here is what follows it: the trash's page, restoring, deleting for good and emptying, and
what a project in the trash still holds (its name, the parts its BOMs name).
"""

from datetime import timedelta
from uuid import uuid7

import pytest

from support.projects import BENCH, World
from wiredex.projects.application.ports import BomUse
from wiredex.projects.application.trash import (
    DeleteProjectForGood,
    EmptyProjectTrash,
    ListTrashedProjects,
    RestoreProject,
)
from wiredex.projects.domain.bom import BomLine, LineContent
from wiredex.projects.domain.designators import Designators
from wiredex.projects.domain.errors import DuplicateProjectNameError, ProjectNotFoundError
from wiredex.projects.domain.filter import ProjectFilter
from wiredex.projects.domain.project import Project, ProjectDetails
from wiredex.projects.domain.values import BomLineId, PartId, ProjectId, ProjectName
from wiredex.shared_kernel.domain.trash import TrashedSlice

pytestmark = pytest.mark.anyio


async def a_trashed_project(world: World, name: str) -> Project:
    project = world.hold_project(name)
    world.clock.advance(timedelta(minutes=1))
    await world.delete_project(BENCH, project.id)
    return project


async def test_the_trash_lists_its_newest_projects_with_how_many_match() -> None:
    world = World()
    first = await a_trashed_project(world, "Weather station")
    second = await a_trashed_project(world, "Greenhouse controller")
    third = await a_trashed_project(world, "Pico blink")
    listed = ListTrashedProjects(world.work.for_workspace)

    assert await listed(BENCH, 2) == TrashedSlice((third, second), 3)
    assert await listed(BENCH, 50) == TrashedSlice((third, second, first), 3)
    assert await listed(BENCH, 50, "STATION") == TrashedSlice((first,), 1)
    assert await listed(BENCH, 50, "_") == TrashedSlice((), 0)


async def test_a_restored_project_is_back_with_its_revisions() -> None:
    world = World()
    project = world.hold_project("Weather station")
    b = world.hold_revision(project, "B", minutes=1)
    await world.delete_project(BENCH, project.id)

    await RestoreProject(world.work.for_workspace)(BENCH, project.id)

    view = await world.get_project(BENCH, project.id)
    assert [revision.label.value for revision in view.revisions.items] == ["A", "B"]
    assert (await world.get_revision(BENCH, b.id)).id == b.id
    listed = await world.list_projects(BENCH, ProjectFilter())
    assert [summary.project.id for summary in listed] == [project.id]


async def test_only_a_project_in_the_trash_is_restored_or_deleted_for_good() -> None:
    # Requirements 5.3 and 6.2: a live project and an unknown one are both not in the trash.
    world = World()
    live = world.hold_project("Weather station")
    work = world.work.for_workspace

    for missing in (live.id, ProjectId(uuid7())):
        with pytest.raises(ProjectNotFoundError, match="isn't in the trash"):
            await RestoreProject(work)(BENCH, missing)
        with pytest.raises(ProjectNotFoundError, match="isn't in the trash"):
            await DeleteProjectForGood(work)(BENCH, missing)

    assert live.id in world.work.projects.saved
    assert world.work.commits == 0


async def test_a_project_deleted_for_good_takes_its_revisions() -> None:
    world = World()
    project = world.hold_project("Weather station")
    world.hold_revision(project, "B", minutes=1)
    await world.delete_project(BENCH, project.id)

    await DeleteProjectForGood(world.work.for_workspace)(BENCH, project.id)

    assert world.work.projects.saved == {}
    assert world.work.revisions.saved == {}


async def test_emptying_the_trash_deletes_only_what_is_in_it() -> None:
    world = World()
    trashed = [await a_trashed_project(world, name) for name in ("Weather station", "Pico")]
    live = world.hold_project("Greenhouse controller")

    emptied = await EmptyProjectTrash(world.work.for_workspace)(BENCH)

    assert emptied == len(trashed)
    assert list(world.work.projects.saved) == [live.id]
    assert {revision.project_id for revision in world.work.revisions.saved.values()} == {live.id}


async def test_a_project_in_the_trash_keeps_its_name() -> None:
    # Requirement 3.1: the unique index still holds it, and the refusal says where it is.
    world = World()
    await a_trashed_project(world, "Weather station")
    other = world.hold_project("Greenhouse controller")

    with pytest.raises(DuplicateProjectNameError, match="Weather station, in the trash"):
        await world.create_project(BENCH, ProjectDetails(ProjectName("weather STATION")))
    with pytest.raises(DuplicateProjectNameError, match="in the trash"):
        await world.update_project(BENCH, other.id, ProjectDetails(ProjectName("Weather station")))


async def test_a_bom_of_a_project_in_the_trash_still_names_its_part() -> None:
    # Requirement 1.2 and decision 4: the use is counted, and marked as in the trash.
    world = World()
    project = world.hold_project("Weather station")
    [revision] = world.work.revisions.saved.values()
    part = PartId(uuid7())
    content = LineContent.of(part, Designators.parse("R1"), None, None)
    line = BomLine.on(revision, BomLineId(uuid7()), content, world.clock.now())
    world.work.bom_lines.saved[line.id] = line
    await world.delete_project(BENCH, project.id)

    uses = await world.work.bom_lines.uses_of(part, 3)

    assert uses.uses == (
        BomUse(project.id, project.name, revision.id, revision.label, in_trash=True),
    )
