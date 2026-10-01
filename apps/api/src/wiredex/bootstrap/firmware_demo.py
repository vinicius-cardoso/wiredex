"""Wiring for the firmware part of `wiredex demo reset` and `wiredex demo invite`.

Kept out of `bootstrap/firmware.py` on purpose, as `projects_demo.py` is kept out of
`bootstrap/projects.py`: this is only the demo's wiring, over an engine of its own for one run
of the command (ADR 0011). The samples are written through `firmware_use_cases`, the wiring the
routes run, so a sample obeys every rule a firmware written in the browser does (13's
requirement 10.2). They run on the sample revisions, so this is also where projects answers
for them: the bench's revisions are read by project name and label through projects'
`ListProjects` and `GetProject`, once the projects' restore has minted their ids (13's decision
15), as `projects_demo.py` reads the sample parts through catalog's `ListParts`.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.firmware import firmware_use_cases
from wiredex.bootstrap.settings import Settings
from wiredex.firmware.application.demo import (
    RestoreSampleFirmware,
    RevisionName,
    SampleFirmwareWrites,
)
from wiredex.firmware.domain.values import RevisionId, WorkspaceId
from wiredex.firmware.infrastructure.unit_of_work import SqlFirmwareUnitOfWork
from wiredex.projects.application.projects import GetProject, ListProjects
from wiredex.projects.domain.filter import ProjectFilter
from wiredex.projects.domain.values import WorkspaceId as ProjectsWorkspaceId
from wiredex.projects.infrastructure.unit_of_work import SqlProjectsUnitOfWork
from wiredex.shared_kernel.infrastructure.ids import Uuid7Generator


@asynccontextmanager
async def restore_sample_firmware_use_case(
    settings: Settings,
) -> AsyncIterator[RestoreSampleFirmware]:
    """RestoreSampleFirmware over Postgres, for one run of a demo command (decision 15)."""
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    use_cases = firmware_use_cases(session_factory)

    def unit_of_work(workspace_id: WorkspaceId) -> SqlFirmwareUnitOfWork:
        # The clear reads no revision, so firmware's own unit of work is enough for it.
        return SqlFirmwareUnitOfWork(session_factory, workspace_id)

    ids = Uuid7Generator()

    def projects_unit_of_work(workspace_id: ProjectsWorkspaceId) -> SqlProjectsUnitOfWork:
        return SqlProjectsUnitOfWork(session_factory, workspace_id, ids)

    list_projects = ListProjects(projects_unit_of_work)
    get_project = GetProject(projects_unit_of_work)

    async def sample_revisions(workspace_id: WorkspaceId) -> dict[RevisionName, RevisionId]:
        """The bench's revisions by project name and label, a page per project (the sample is
        tiny). A project's name is unique in its bench and a label in its project, so the two
        find one revision."""
        # The same UUID under each module's own name: neither imports the other's domain.
        bench = ProjectsWorkspaceId(workspace_id)
        found: dict[RevisionName, RevisionId] = {}
        for row in await list_projects(bench, ProjectFilter()):
            view = await get_project(bench, row.project.id)
            for revision in view.revisions.items:
                name = RevisionName(str(view.project.name), str(revision.label))
                found[name] = RevisionId(revision.id)
        return found

    try:
        yield RestoreSampleFirmware(
            unit_of_work,
            SampleFirmwareWrites(
                create_firmware=use_cases.create_firmware,
                link_revision=use_cases.link_revision,
                start_version=use_cases.start_version,
                add_source_files=use_cases.add_source_files,
                update_source_file=use_cases.update_source_file,
                update_version=use_cases.update_version,
                release_version=use_cases.release_version,
            ),
            sample_revisions,
        )
    finally:
        await engine.dispose()
