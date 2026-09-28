"""Projects: create, edit, delete, open one, list them, and the workspace's tags.

A project is never without a revision (decision 2), so creating one writes revision A in the
same transaction, and the page and the list can always name a latest revision.
"""

from collections.abc import Callable
from datetime import datetime

from wiredex.projects.application.ports import (
    ProjectSummary,
    ProjectsUnitOfWork,
    ProjectView,
    TagCount,
)
from wiredex.projects.domain.errors import DuplicateProjectNameError, ProjectNotFoundError
from wiredex.projects.domain.filter import ProjectFilter
from wiredex.projects.domain.project import Project, ProjectDetails
from wiredex.projects.domain.project_revisions import ProjectRevisions
from wiredex.projects.domain.revision import Revision, RevisionDetails
from wiredex.projects.domain.values import (
    ProjectId,
    ProjectName,
    RevisionId,
    RevisionLabel,
    WorkspaceId,
)
from wiredex.shared_kernel.application.ports import Clock, IdGenerator

type UnitOfWorkFactory = Callable[[WorkspaceId], ProjectsUnitOfWork]


class CreateProject:
    def __init__(self, unit_of_work: UnitOfWorkFactory, clock: Clock, ids: IdGenerator) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._ids = ids

    async def __call__(self, workspace_id: WorkspaceId, details: ProjectDetails) -> ProjectView:
        async with self._unit_of_work(workspace_id) as work:
            await _check_name_free(work, details.name)
            now = self._clock.now()
            project = Project.start(ProjectId(self._ids.new_id()), workspace_id, details, now)
            first = Revision.draft(
                RevisionId(self._ids.new_id()),
                project,
                RevisionDetails(RevisionLabel.first()),
                now,
            )
            await work.projects.add(project)
            await work.revisions.add(first)
            await work.commit()
            return ProjectView(project, ProjectRevisions((first,)))


class UpdateProject:
    """Replaces a project's name, description and tags whole (requirement 1.5)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory, clock: Clock) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    async def __call__(
        self, workspace_id: WorkspaceId, project_id: ProjectId, details: ProjectDetails
    ) -> ProjectView:
        async with self._unit_of_work(workspace_id) as work:
            project = await load_project(work, project_id)
            await _check_name_free(work, details.name, keeping=project)
            if project.revise(details, self._clock.now()):
                await work.commit()
            return ProjectView(project, await work.revisions.of_project(project.id))


class DeleteProject:
    """The project and its revisions together, while every revision is a draft (1.7, 1.8)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId, project_id: ProjectId) -> None:
        async with self._unit_of_work(workspace_id) as work:
            # Locked before its revisions are read, so none can be added or moved out of draft
            # between the check and the delete.
            project = await lock_project(work, project_id)
            revisions = await work.revisions.of_project(project.id)
            revisions.ensure_all_deletable()
            await work.projects.remove(project)
            await work.commit()


class GetProject:
    """A project page in two reads, whatever the number of revisions (requirement 11.3)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId, project_id: ProjectId) -> ProjectView:
        async with self._unit_of_work(workspace_id) as work:
            project = await load_project(work, project_id)
            return ProjectView(project, await work.revisions.of_project(project.id))


class ListProjects:
    """The projects matching a filter, freshest first, in two reads whatever their number
    (requirements 3.1, 3.2, 11.3)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(
        self, workspace_id: WorkspaceId, wanted: ProjectFilter
    ) -> list[ProjectSummary]:
        async with self._unit_of_work(workspace_id) as work:
            projects = await work.projects.matching(wanted)
            revisions = await work.revisions.of_projects([project.id for project in projects])
            summaries = [
                summary
                for project in projects
                if (summary := _summary(project, revisions.get(project.id))) is not None
            ]
            # Newest first, and the id, time-ordered too, keeps two projects touched at one
            # instant in a stable order.
            summaries.sort(key=lambda row: (row.last_activity, row.project.id), reverse=True)
            return summaries


class ListProjectTags:
    """The workspace's tags with their counts, for the tag box and the list's chips (2.6)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId) -> list[TagCount]:
        async with self._unit_of_work(workspace_id) as work:
            return await work.projects.tag_counts()


async def load_project(work: ProjectsUnitOfWork, project_id: ProjectId) -> Project:
    """The project, or a 404. Another workspace's id is simply not found (requirement 8.2)."""
    project = await work.projects.get(project_id)
    if project is None:
        raise ProjectNotFoundError("that project doesn't exist")
    return project


async def lock_project(work: ProjectsUnitOfWork, project_id: ProjectId) -> Project:
    """The project with its row locked until the transaction ends, or a 404 (decision 15)."""
    project = await work.projects.locked(project_id)
    if project is None:
        raise ProjectNotFoundError("that project doesn't exist")
    return project


async def _check_name_free(
    work: ProjectsUnitOfWork, name: ProjectName, keeping: Project | None = None
) -> None:
    """Requirement 1.3. A project renamed to its own name in another case still holds it, so
    `keeping` is never in its own way."""
    holder = await work.projects.named(name)
    if holder is not None and (keeping is None or holder.id != keeping.id):
        raise DuplicateProjectNameError(f"there is already a project named {holder.name}")


def _summary(project: Project, revisions: ProjectRevisions | None) -> ProjectSummary | None:
    """A list row, or None for a project whose revisions went between the list's two reads:
    only deleting the project takes its last one, so it is gone too."""
    latest = None if revisions is None else revisions.latest
    if revisions is None or latest is None:
        return None
    return ProjectSummary(
        project=project,
        latest=latest,
        revision_count=len(revisions.items),
        last_activity=_last_activity(project, revisions),
    )


def _last_activity(project: Project, revisions: ProjectRevisions) -> datetime:
    """The later of the project's own date and its revisions' (decision 11): a revision's edit
    moves its project up the list without writing the project row."""
    return max(project.updated_at, *(revision.updated_at for revision in revisions.items))
