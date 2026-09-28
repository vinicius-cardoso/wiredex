"""Wire the projects module: every use case over Postgres.

Projects asks nothing of another module (the independence contract), so this is only the unit
of work, a clock and an id generator. `files` will ask projects whether a project or a
revision exists through bootstrap, from `get_project` and `get_revision` (design decision 12).
"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from wiredex.projects.api.router import ProjectsUseCases
from wiredex.projects.application.projects import (
    CreateProject,
    DeleteProject,
    GetProject,
    ListProjects,
    ListProjectTags,
    UpdateProject,
)
from wiredex.projects.application.revisions import (
    AddRevision,
    DeleteRevision,
    ForkRevision,
    GetRevision,
    UpdateRevision,
)
from wiredex.projects.domain.values import WorkspaceId
from wiredex.projects.infrastructure.unit_of_work import SqlProjectsUnitOfWork
from wiredex.shared_kernel.infrastructure.clock import SystemClock
from wiredex.shared_kernel.infrastructure.ids import Uuid7Generator

type SessionFactory = async_sessionmaker[AsyncSession]


def projects_use_cases(session_factory: SessionFactory) -> ProjectsUseCases:
    """The projects use cases, wired to Postgres."""

    def unit_of_work(workspace_id: WorkspaceId) -> SqlProjectsUnitOfWork:
        # One unit of work per workspace, as every module's is: the id reaches both of ADR
        # 0007's gates, the repositories' filters and the policies Postgres reads it in.
        return SqlProjectsUnitOfWork(session_factory, workspace_id)

    clock, ids = SystemClock(), Uuid7Generator()
    return ProjectsUseCases(
        create_project=CreateProject(unit_of_work, clock, ids),
        update_project=UpdateProject(unit_of_work, clock),
        delete_project=DeleteProject(unit_of_work),
        get_project=GetProject(unit_of_work),
        list_projects=ListProjects(unit_of_work),
        list_project_tags=ListProjectTags(unit_of_work),
        add_revision=AddRevision(unit_of_work, clock, ids),
        fork_revision=ForkRevision(unit_of_work, clock, ids),
        update_revision=UpdateRevision(unit_of_work, clock),
        delete_revision=DeleteRevision(unit_of_work, clock),
        get_revision=GetRevision(unit_of_work),
    )
