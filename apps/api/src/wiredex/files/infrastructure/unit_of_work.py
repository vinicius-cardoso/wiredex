from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from wiredex.files.domain.values import WorkspaceId
from wiredex.files.infrastructure.repositories import SqlAttachments, SqlFiles
from wiredex.shared_kernel.infrastructure.unit_of_work import SqlUnitOfWork


class SqlFilesUnitOfWork(SqlUnitOfWork):
    """One transaction with the files repositories bound to its session and workspace.

    The workspace is required, as the catalog's is: every files row belongs to one, and both
    of ADR 0007's gates need it — the repositories filter on it, and the base names it to
    Postgres so the policies on `files` and `attachments` apply. `files` and `attachments`
    are attributes here but the `FilesUnitOfWork` port reads them as properties, which a
    plain attribute satisfies (the port is a Protocol, so structural).
    """

    files: SqlFiles
    attachments: SqlAttachments

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        workspace_id: WorkspaceId,
    ) -> None:
        super().__init__(session_factory, workspace_id)
        # Kept under its own name: the base holds a plain UUID, and the repositories speak
        # the files module's WorkspaceId.
        self._workspace = workspace_id

    async def __aenter__(self) -> Self:
        await super().__aenter__()
        self.files = SqlFiles(self.session, self._workspace)
        self.attachments = SqlAttachments(self.session, self._workspace)
        return self
