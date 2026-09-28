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
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.settings import FileStore, Settings
from wiredex.catalog.application.parts import GetPart
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
from wiredex.identity.domain.values import WorkspaceId as IdentityWorkspaceId
from wiredex.identity.domain.values import WorkspaceKind
from wiredex.identity.infrastructure.unit_of_work import SqlIdentityUnitOfWork
from wiredex.projects.application.projects import GetProject
from wiredex.projects.application.revisions import GetRevision
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


class AttachmentSubjects:
    """`Subjects` over the module each kind belongs to (design §3, 08's decision 12): a part
    is asked of catalog's `GetPart`, a project of projects' `GetProject`, a revision of its
    `GetRevision`, each read-only in a transaction of its own.

    A subject that isn't there — deleted, never created, or another workspace's — is its
    module's not-found error, which reads as "no such subject", so the prune drops its
    attachments and an upload to it is refused (requirements 1.5, 4.4; 08's 7.6, 7.8). The id
    is only ever read as the kind says: a project's id named as a part is no part.
    """

    def __init__(
        self, get_part: GetPart, get_project: GetProject, get_revision: GetRevision
    ) -> None:
        self._get_part = get_part
        self._get_project = get_project
        self._get_revision = get_revision

    async def exists(self, workspace_id: WorkspaceId, subject: Subject) -> bool:
        try:
            await self._look_up(workspace_id, subject)
        except PartNotFoundError, ProjectNotFoundError, RevisionNotFoundError:
            return False
        return True

    async def _look_up(self, workspace_id: WorkspaceId, subject: Subject) -> None:
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
    return AttachmentSubjects(GetPart(catalog), GetProject(projects), GetRevision(projects))


def _catalog_unit_of_work(
    session_factory: SessionFactory,
) -> Callable[[CatalogWorkspaceId], SqlCatalogUnitOfWork]:
    return lambda workspace_id: SqlCatalogUnitOfWork(session_factory, workspace_id)


def _projects_unit_of_work(
    session_factory: SessionFactory,
) -> Callable[[ProjectsWorkspaceId], SqlProjectsUnitOfWork]:
    return lambda workspace_id: SqlProjectsUnitOfWork(session_factory, workspace_id)


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
