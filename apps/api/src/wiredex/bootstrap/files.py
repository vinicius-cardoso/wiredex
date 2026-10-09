"""Wire the files module: the store from settings, the two cross-module ports, the use cases.

`files` imports none of catalog, projects and identity (the independence contract forbids
it): this composition root is the one place that knows them all, so it implements the
`Subjects` and `Quotas` ports here and hands them to the use cases (design §3). `Subjects`
asks catalog whether a part exists and projects whether a project or a revision does;
`Quotas` reads the workspace's kind from identity.

The store is a `LocalFileStore` in development and the tests and an `S3FileStore` in
production, chosen from `WIREDEX_FILE_STORE`; a use case never knows which one it holds.
"""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.settings import FileStore, Settings
from wiredex.catalog.application.parts import GetPart
from wiredex.catalog.application.trash import PartIsKept
from wiredex.catalog.domain.errors import PartNotFoundError
from wiredex.catalog.domain.values import PartDefinitionId
from wiredex.catalog.domain.values import WorkspaceId as CatalogWorkspaceId
from wiredex.catalog.infrastructure.unit_of_work import SqlCatalogUnitOfWork
from wiredex.files.api.router import FilesUseCases
from wiredex.files.application.attachments import (
    Attach,
    ChangeAttachment,
    ClearWorkspace,
    Detach,
    FilesServices,
    ListAttachments,
    OpenAttachment,
    PruneOrphans,
)
from wiredex.files.application.ports import FileStore as FileStorePort
from wiredex.files.domain.values import Subject, SubjectKind, WorkspaceId
from wiredex.files.infrastructure.stores import LocalFileStore, S3FileStore, s3_client
from wiredex.files.infrastructure.unit_of_work import SqlFilesUnitOfWork
from wiredex.firmware.application.versions import VersionIsKept, VersionIsReleased
from wiredex.firmware.domain.values import VersionId
from wiredex.firmware.domain.values import WorkspaceId as FirmwareWorkspaceId
from wiredex.firmware.infrastructure.unit_of_work import SqlFirmwareUnitOfWork
from wiredex.identity.domain.values import WorkspaceId as IdentityWorkspaceId
from wiredex.identity.domain.values import WorkspaceKind
from wiredex.identity.infrastructure.unit_of_work import SqlIdentityUnitOfWork
from wiredex.projects.application.projects import GetProject
from wiredex.projects.application.revisions import GetRevision
from wiredex.projects.application.trash import ProjectIsKept, RevisionIsKept
from wiredex.projects.domain.errors import ProjectNotFoundError, RevisionNotFoundError
from wiredex.projects.domain.values import ProjectId, RevisionId
from wiredex.projects.domain.values import WorkspaceId as ProjectsWorkspaceId
from wiredex.projects.infrastructure.unit_of_work import SqlProjectsUnitOfWork
from wiredex.shared_kernel.infrastructure.clock import SystemClock
from wiredex.shared_kernel.infrastructure.ids import Uuid7Generator

# Requirement 2.7: a demo bench may store 25 MB, the owner's personal workspace 5 GB.
DEMO_QUOTA = 25 * 1000 * 1000
PERSONAL_QUOTA = 5 * 1000 * 1000 * 1000

type SessionFactory = async_sessionmaker[AsyncSession]


@dataclass(frozen=True, slots=True)
class SubjectReads:
    """The reads `AttachmentSubjects` asks of catalog, projects and firmware: whether each kind
    of subject is live, and whether it is kept, live or in the trash."""

    get_part: GetPart
    get_project: GetProject
    get_revision: GetRevision
    version_is_released: VersionIsReleased
    part_is_kept: PartIsKept
    project_is_kept: ProjectIsKept
    revision_is_kept: RevisionIsKept
    version_is_kept: VersionIsKept


class AttachmentSubjects:
    """`Subjects` over the module each kind belongs to (design §3, 08's decision 12): a part
    is asked of catalog's `GetPart`, a project of projects' `GetProject`, a revision of its
    `GetRevision`, each read-only in a transaction of its own. A firmware version is asked of
    firmware's `VersionIsReleased`: only a released one takes a build, so a draft is absent
    here as a version that doesn't exist is (20-firmware-builds, decision 3).

    A subject that isn't there — deleted, never created, or another workspace's — is its
    module's not-found error, which reads as "no such subject", so the prune drops its
    attachments and an upload to it is refused (requirements 1.5, 4.4; 08's 7.6, 7.8). The id
    is only ever read as the kind says: a project's id named as a part is no part.
    """

    def __init__(self, reads: SubjectReads) -> None:
        self._get_part = reads.get_part
        self._get_project = reads.get_project
        self._get_revision = reads.get_revision
        self._kept = reads

    async def exists(self, workspace_id: WorkspaceId, subject: Subject) -> bool:
        if subject.kind is SubjectKind.FIRMWARE_VERSION:
            return await self._kept.version_is_released(
                FirmwareWorkspaceId(workspace_id), VersionId(subject.id)
            )
        try:
            await self._look_up(workspace_id, subject)
        except PartNotFoundError, ProjectNotFoundError, RevisionNotFoundError:
            return False
        return True

    async def kept(self, workspace_id: WorkspaceId, subject: Subject) -> bool:
        """Whether the subject's row is still there, in the trash or not: the prune keeps a
        record's attachments until it is deleted for good (16-soft-delete-and-trash, decision
        7)."""
        match subject.kind:
            case SubjectKind.PART:
                part_id = PartDefinitionId(subject.id)
                return await self._kept.part_is_kept(CatalogWorkspaceId(workspace_id), part_id)
            case SubjectKind.PROJECT:
                project_id = ProjectId(subject.id)
                return await self._kept.project_is_kept(
                    ProjectsWorkspaceId(workspace_id), project_id
                )
            case SubjectKind.REVISION:
                revision_id = RevisionId(subject.id)
                return await self._kept.revision_is_kept(
                    ProjectsWorkspaceId(workspace_id), revision_id
                )
            case SubjectKind.FIRMWARE_VERSION:
                return await self._kept.version_is_kept(
                    FirmwareWorkspaceId(workspace_id), VersionId(subject.id)
                )

    async def _look_up(self, workspace_id: WorkspaceId, subject: Subject) -> None:
        """The part, project or revision, read as its module reads it: its not-found error
        when it isn't there. A firmware version never comes here: `exists` asks it directly."""
        match subject.kind:
            case SubjectKind.PART:
                await self._get_part(CatalogWorkspaceId(workspace_id), PartDefinitionId(subject.id))
            case SubjectKind.PROJECT:
                await self._get_project(ProjectsWorkspaceId(workspace_id), ProjectId(subject.id))
            case SubjectKind.REVISION:
                await self._get_revision(ProjectsWorkspaceId(workspace_id), RevisionId(subject.id))


class KindQuotas:
    """`Quotas` over identity's workspace kind: a demo bench gets 25 MB, the owner 5 GB (2.7).

    A workspace identity doesn't know is given the demo quota: it is the smaller of the two,
    so an unknown one can never store more than the least-trusted real one.
    """

    def __init__(self, unit_of_work: Callable[[], SqlIdentityUnitOfWork]) -> None:
        self._unit_of_work = unit_of_work

    async def limit_for(self, workspace_id: WorkspaceId) -> int:
        async with self._unit_of_work() as work:
            workspace = await work.workspaces.get(IdentityWorkspaceId(workspace_id))
        if workspace is not None and workspace.kind is WorkspaceKind.PERSONAL:
            return PERSONAL_QUOTA
        return DEMO_QUOTA


def create_file_store(settings: Settings) -> FileStorePort:
    """The store `WIREDEX_FILE_STORE` names: a local folder, or an S3-compatible bucket.

    In production the settings validator has already refused to start unless the store is
    `s3` and every S3 setting is set (requirement 7.1), so the values read here are present.
    """
    if settings.file_store is FileStore.S3:
        client = s3_client(
            settings.files_endpoint,
            settings.files_region,
            settings.files_access_key,
            settings.files_secret_key.get_secret_value(),
        )
        return S3FileStore(settings.files_bucket, client)
    return LocalFileStore(Path(settings.files_dir))


def files_use_cases(session_factory: SessionFactory, store: FileStorePort) -> FilesUseCases:
    """The files use cases, wired to Postgres, the configured store and the two ports."""

    def files_unit_of_work(workspace_id: WorkspaceId) -> SqlFilesUnitOfWork:
        # One unit of work per workspace, as catalog's is: the id reaches both of ADR 0007's
        # gates — the repositories filter on it and Postgres reads it in its policies.
        return SqlFilesUnitOfWork(session_factory, workspace_id)

    def identity_unit_of_work() -> SqlIdentityUnitOfWork:
        return SqlIdentityUnitOfWork(session_factory)

    subjects = _attachment_subjects(session_factory)
    quotas = KindQuotas(identity_unit_of_work)
    services = FilesServices(store, subjects, quotas, SystemClock(), Uuid7Generator())
    return FilesUseCases(
        attach=Attach(files_unit_of_work, services),
        list_attachments=ListAttachments(files_unit_of_work),
        open_attachment=OpenAttachment(files_unit_of_work, store),
        change_attachment=ChangeAttachment(files_unit_of_work),
        detach=Detach(files_unit_of_work, store),
        clear_workspace=ClearWorkspace(files_unit_of_work, store),
        prune_orphans=PruneOrphans(files_unit_of_work, subjects, store, SystemClock()),
    )


def _attachment_subjects(session_factory: SessionFactory) -> AttachmentSubjects:
    """Each subject kind asked of its own module, over the same database as files."""
    catalog = _catalog_unit_of_work(session_factory)
    projects = _projects_unit_of_work(session_factory)

    def firmware(workspace_id: FirmwareWorkspaceId) -> SqlFirmwareUnitOfWork:
        return SqlFirmwareUnitOfWork(session_factory, workspace_id)

    reads = SubjectReads(
        get_part=GetPart(catalog),
        get_project=GetProject(projects),
        get_revision=GetRevision(projects),
        version_is_released=VersionIsReleased(firmware),
        part_is_kept=PartIsKept(catalog),
        project_is_kept=ProjectIsKept(projects),
        revision_is_kept=RevisionIsKept(projects),
        version_is_kept=VersionIsKept(firmware),
    )
    return AttachmentSubjects(reads)


def _catalog_unit_of_work(
    session_factory: SessionFactory,
) -> Callable[[CatalogWorkspaceId], SqlCatalogUnitOfWork]:
    return lambda workspace_id: SqlCatalogUnitOfWork(session_factory, workspace_id)


def _projects_unit_of_work(
    session_factory: SessionFactory,
) -> Callable[[ProjectsWorkspaceId], SqlProjectsUnitOfWork]:
    # The subjects only read, but the unit of work takes the ids a fork's copied lines get.
    ids = Uuid7Generator()
    return lambda workspace_id: SqlProjectsUnitOfWork(session_factory, workspace_id, ids)


def _files_unit_of_work(
    session_factory: SessionFactory,
) -> Callable[[WorkspaceId], SqlFilesUnitOfWork]:
    # One unit of work per workspace, as in files_use_cases: the id reaches both of ADR
    # 0007's gates — the repositories filter on it and Postgres reads it in its policies.
    return lambda workspace_id: SqlFilesUnitOfWork(session_factory, workspace_id)


@asynccontextmanager
async def prune_orphans_use_case(settings: Settings) -> AsyncIterator[PruneOrphans]:
    """PruneOrphans over Postgres and the configured store, for one `wiredex files prune`.

    The nightly sweep (ADR 0011): each workspace's orphaned attachments, unused file rows
    and stray objects. `AttachmentSubjects` tells it which parts, projects and revisions
    survive.
    """
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    store = create_file_store(settings)
    try:
        subjects = _attachment_subjects(session_factory)
        yield PruneOrphans(_files_unit_of_work(session_factory), subjects, store, SystemClock())
    finally:
        await engine.dispose()


@asynccontextmanager
async def clear_workspace_use_case(settings: Settings) -> AsyncIterator[ClearWorkspace]:
    """ClearWorkspace over Postgres and the configured store, for one run of a demo reset.

    Wipes a demo bench's files clean before the sample catalog is restored (requirement
    5.3), next to identity's guest removal and catalog's reseeding in `wiredex demo reset`.
    """
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    store = create_file_store(settings)
    try:
        yield ClearWorkspace(_files_unit_of_work(session_factory), store)
    finally:
        await engine.dispose()
