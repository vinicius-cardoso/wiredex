"""Wire the files module: the store from settings, the two cross-module ports, the use cases.

`files` imports neither catalog nor identity (the independence contract forbids it): this
composition root is the one place that knows all three, so it implements the `Subjects` and
`Quotas` ports here and hands them to the use cases (design §3). `Subjects` asks catalog's
`GetPart` whether a part exists; `Quotas` reads the workspace's kind from identity.

The store is a `LocalFileStore` in development and the tests and an `S3FileStore` in
production, chosen from `WIREDEX_FILE_STORE`; a use case never knows which one it holds.
"""

from collections.abc import Callable
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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
from wiredex.files.domain.values import Subject, WorkspaceId
from wiredex.files.infrastructure.stores import LocalFileStore, S3FileStore, s3_client
from wiredex.files.infrastructure.unit_of_work import SqlFilesUnitOfWork
from wiredex.identity.domain.values import WorkspaceId as IdentityWorkspaceId
from wiredex.identity.domain.values import WorkspaceKind
from wiredex.identity.infrastructure.unit_of_work import SqlIdentityUnitOfWork
from wiredex.shared_kernel.infrastructure.clock import SystemClock
from wiredex.shared_kernel.infrastructure.ids import Uuid7Generator

# Requirement 2.7: a demo bench may store 25 MB, the owner's personal workspace 5 GB.
DEMO_QUOTA = 25 * 1000 * 1000
PERSONAL_QUOTA = 5 * 1000 * 1000 * 1000

type SessionFactory = async_sessionmaker[AsyncSession]


class CatalogSubjects:
    """`Subjects` over catalog's `GetPart`: does `part:<id>` exist in this workspace? (design §3).

    A part that isn't there — deleted, never created, or another workspace's — is a
    `PartNotFoundError`, which reads as "no such subject" so the prune drops its attachments
    and an upload to it is refused (requirements 1.5, 4.4). Only `part` subjects exist today.
    """

    def __init__(self, get_part: GetPart) -> None:
        self._get_part = get_part

    async def exists(self, workspace_id: WorkspaceId, subject: Subject) -> bool:
        part_id = PartDefinitionId(subject.id)
        try:
            await self._get_part(CatalogWorkspaceId(workspace_id), part_id)
        except PartNotFoundError:
            return False
        return True


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

    subjects = CatalogSubjects(GetPart(_catalog_unit_of_work(session_factory)))
    quotas = KindQuotas(identity_unit_of_work)
    services = FilesServices(store, subjects, quotas, SystemClock(), Uuid7Generator())
    return FilesUseCases(
        attach=Attach(files_unit_of_work, services),
        list_attachments=ListAttachments(files_unit_of_work),
        open_attachment=OpenAttachment(files_unit_of_work, store),
        change_attachment=ChangeAttachment(files_unit_of_work),
        detach=Detach(files_unit_of_work, store),
        clear_workspace=ClearWorkspace(files_unit_of_work, store),
        prune_orphans=PruneOrphans(files_unit_of_work, subjects, store),
    )


def _catalog_unit_of_work(
    session_factory: SessionFactory,
) -> Callable[[CatalogWorkspaceId], SqlCatalogUnitOfWork]:
    return lambda workspace_id: SqlCatalogUnitOfWork(session_factory, workspace_id)
