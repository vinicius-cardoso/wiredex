"""Projects' share of the trash: the projects in it, and bringing one back or deleting it for good.

Moving a project to the trash is `DeleteProject`, refused while a revision holds stock
(16-soft-delete-and-trash, decision 4). What follows it is here, one use case each, which bootstrap
wraps in the trash module's bin for projects (decision 8). A project's revisions, BOMs and
netlists have no state of their own: they are in the trash with it and come back with it.
Restoring and deleting for good each lock the project first, so the two take turns and the second
finds nothing (decision 10).
"""

from wiredex.projects.application.ports import ProjectsUnitOfWork
from wiredex.projects.application.projects import UnitOfWorkFactory
from wiredex.projects.domain.errors import ProjectNotFoundError
from wiredex.projects.domain.project import Project
from wiredex.projects.domain.values import ProjectId, RevisionId, WorkspaceId
from wiredex.shared_kernel.domain.trash import TrashPosition


class ListTrashedProjects:
    """One page of the projects in the trash, newest first (requirement 4.1)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(
        self, workspace_id: WorkspaceId, before: TrashPosition | None, limit: int
    ) -> list[Project]:
        async with self._unit_of_work(workspace_id) as work:
            return await work.projects.trashed(before, limit)


class RestoreProject:
    """A project back from the trash with its revisions, as it was (requirement 5.1)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId, project_id: ProjectId) -> None:
        async with self._unit_of_work(workspace_id) as work:
            project = await _in_trash(work, project_id)
            project.restore_from_trash()
            await work.commit()


class DeleteProjectForGood:
    """A project in the trash deleted with its revisions, BOMs and nets, as deleting a project
    did before (requirement 6.1)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId, project_id: ProjectId) -> None:
        async with self._unit_of_work(workspace_id) as work:
            project = await _in_trash(work, project_id)
            await work.projects.remove(project)
            await work.commit()


class EmptyProjectTrash:
    """Every project in the trash deleted for good, in one statement (requirement 6.4)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId) -> int:
        async with self._unit_of_work(workspace_id) as work:
            emptied = await work.projects.empty_trash()
            await work.commit()
            return emptied


class ProjectIsKept:
    """Whether the workspace still holds a project, live or in the trash: what the files prune
    asks before it sweeps a project's photos (16's decision 7)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId, project_id: ProjectId) -> bool:
        async with self._unit_of_work(workspace_id) as work:
            return await work.projects.kept(project_id)


class RevisionIsKept:
    """Whether the workspace still holds a revision, its project live or in the trash: what the
    files prune asks before it sweeps a revision's files (16's decision 7)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId, revision_id: RevisionId) -> bool:
        async with self._unit_of_work(workspace_id) as work:
            return await work.revisions.kept(revision_id)


async def _in_trash(work: ProjectsUnitOfWork, project_id: ProjectId) -> Project:
    """The project, locked, if it is in the trash; a 404 for one that isn't, another workspace's
    included (requirements 5.3, 6.2)."""
    project = await work.projects.in_trash(project_id)
    if project is None:
        raise ProjectNotFoundError("that project isn't in the trash")
    return project
