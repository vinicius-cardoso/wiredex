"""One transaction across firmware and projects, for the revisions a firmware runs on.

The one file that sees both modules for them (13-firmware-versions decision 5, requirement
12.1). Firmware declares `RevisionDirectory` as a property of its `RunsOnUnitOfWork` and imports
nothing from projects. Projects offers `SqlRevisions.refs`, 10's one read joining revisions to
their projects, over whichever session it is handed. This file joins them: 07's shared-session
pattern again, with firmware's unit of work opening the session and projects' repository
joining it.

A firmware's page, a revision's firmware, a link and a firmware created for a revision read the
revisions in the transaction firmware opened, on its connection, under the one workspace
setting it applied, so row-level security scopes both modules' rows and a read is one
transaction (decision 12). Nothing locks projects' rows: a revision deleted by another request
after a link checked it leaves a link the reads already leave out (decision 3).

`firmware_use_cases` builds every firmware use case over that one unit of work, for the app's
router.
"""

from collections.abc import Collection, Mapping
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from wiredex.firmware.api.router import FirmwareUseCases
from wiredex.firmware.application.firmware import (
    CreateFirmware,
    DeleteFirmware,
    GetFirmware,
    ListFirmware,
    ListRevisionFirmware,
    UpdateFirmware,
)
from wiredex.firmware.application.links import LinkRevision, UnlinkRevision
from wiredex.firmware.application.ports import RevisionFacts
from wiredex.firmware.application.sources import (
    AddSourceFiles,
    RemoveSourceFile,
    UpdateSourceFile,
)
from wiredex.firmware.application.versions import (
    DeleteVersion,
    GetVersion,
    ReleaseVersion,
    StartVersion,
    UpdateVersion,
)
from wiredex.firmware.domain.values import RevisionId, WorkspaceId
from wiredex.firmware.infrastructure.unit_of_work import SqlFirmwareUnitOfWork
from wiredex.projects.application.ports import RevisionRef
from wiredex.projects.domain.values import RevisionId as ProjectsRevisionId
from wiredex.projects.domain.values import WorkspaceId as ProjectsWorkspaceId
from wiredex.projects.infrastructure.repositories import SqlRevisions
from wiredex.shared_kernel.infrastructure.clock import SystemClock
from wiredex.shared_kernel.infrastructure.ids import Uuid7Generator

type SessionFactory = async_sessionmaker[AsyncSession]


class ProjectsRevisionDirectory:
    """Firmware's `RevisionDirectory` over projects' `SqlRevisions.refs`, on firmware's session.

    Each `RevisionRef` becomes firmware's own `RevisionFacts`: the ids as the same UUIDs under
    firmware's names, and the project's name, the label and the summary as text. The status
    stays behind, since firmware reads none: a link is made whatever the revision's status
    (decision 2). A revision the workspace doesn't hold, another bench's or a deleted one, is
    absent, as `refs` leaves it out.
    """

    def __init__(self, revisions: SqlRevisions) -> None:
        self._revisions = revisions

    async def refs(
        self, revision_ids: Collection[RevisionId]
    ) -> Mapping[RevisionId, RevisionFacts]:
        # The same UUIDs under each module's own name: neither imports the other's domain.
        found = await self._revisions.refs(
            [ProjectsRevisionId(revision_id) for revision_id in revision_ids]
        )
        return {RevisionId(revision_id): _facts(ref) for revision_id, ref in found.items()}


class SqlRunsOnUnitOfWork(SqlFirmwareUnitOfWork):
    """Firmware's unit of work with projects' revisions bound on its session (decision 5).

    A `RunsOnUnitOfWork`: the base opens the session, sets `app.workspace_id` for the
    transaction and binds firmware's repositories. Projects' `SqlRevisions` then joins that
    same session under the same workspace, wrapped as `ProjectsRevisionDirectory`. It is a
    `FirmwareUnitOfWork` too, so one factory of it serves every firmware use case. Commit and
    rollback stay the base's.
    """

    revisions: ProjectsRevisionDirectory

    async def __aenter__(self) -> Self:
        await super().__aenter__()
        # The same UUID under each module's own name: neither imports the other's domain.
        projects = SqlRevisions(self.session, ProjectsWorkspaceId(self._workspace))
        self.revisions = ProjectsRevisionDirectory(projects)
        return self


def firmware_use_cases(session_factory: SessionFactory) -> FirmwareUseCases:
    """The firmware use cases, wired to Postgres, each over `SqlRunsOnUnitOfWork`."""

    clock, ids = SystemClock(), Uuid7Generator()

    def unit_of_work(workspace_id: WorkspaceId) -> SqlRunsOnUnitOfWork:
        # One unit of work per workspace, as every module's is, and one kind for every use case:
        # it is a `FirmwareUnitOfWork` as well as a `RunsOnUnitOfWork` (decision 5).
        return SqlRunsOnUnitOfWork(session_factory, workspace_id)

    return FirmwareUseCases(
        create_firmware=CreateFirmware(unit_of_work, clock, ids),
        update_firmware=UpdateFirmware(unit_of_work, clock),
        delete_firmware=DeleteFirmware(unit_of_work),
        get_firmware=GetFirmware(unit_of_work),
        list_firmware=ListFirmware(unit_of_work),
        list_revision_firmware=ListRevisionFirmware(unit_of_work),
        link_revision=LinkRevision(unit_of_work, clock),
        unlink_revision=UnlinkRevision(unit_of_work, clock),
        start_version=StartVersion(unit_of_work, clock, ids),
        update_version=UpdateVersion(unit_of_work, clock),
        release_version=ReleaseVersion(unit_of_work, clock),
        delete_version=DeleteVersion(unit_of_work, clock),
        get_version=GetVersion(unit_of_work),
        add_source_files=AddSourceFiles(unit_of_work, clock, ids),
        update_source_file=UpdateSourceFile(unit_of_work, clock),
        remove_source_file=RemoveSourceFile(unit_of_work, clock),
    )


def _facts(ref: RevisionRef) -> RevisionFacts:
    return RevisionFacts(
        revision_id=RevisionId(ref.revision_id),
        project_id=ref.project_id,
        project_name=str(ref.project_name),
        label=str(ref.label),
        summary=None if ref.summary is None else str(ref.summary),
    )
