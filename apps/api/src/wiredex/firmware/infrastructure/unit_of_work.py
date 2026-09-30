from typing import Self

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from wiredex.firmware.domain.values import WorkspaceId
from wiredex.firmware.infrastructure.orm import (
    firmware_revisions,
    firmware_table,
    firmware_versions,
    source_files,
)
from wiredex.firmware.infrastructure.repositories import (
    SqlFirmwares,
    SqlRevisionLinks,
    SqlSources,
    SqlVersions,
)
from wiredex.shared_kernel.infrastructure.unit_of_work import SqlUnitOfWork

# Deleted in foreign-key order for a demo reset: files point at versions, versions and links at
# the firmware. The cascades would take them anyway; naming them keeps the order readable as the
# keys are.
_CLEAR_ORDER = (source_files, firmware_versions, firmware_revisions, firmware_table)


class SqlFirmwareRepositories:
    """Firmware's links bound to a session, which may be someone else's (decision 4).

    Bootstrap builds it over the session a fork's unit of work opened, so the fork copies its
    source's links in projects' transaction. Nothing here opens, commits or scopes a
    transaction: whoever opened the session did, and every query still filters on
    `workspace_id` itself, ADR 0007's first gate.
    """

    links: SqlRevisionLinks

    def __init__(self, session: AsyncSession, workspace_id: WorkspaceId) -> None:
        self.links = SqlRevisionLinks(session, workspace_id)


class SqlFirmwareUnitOfWork(SqlUnitOfWork):
    """One transaction with the firmware repositories bound to its session and workspace.

    The workspace is required here, unlike in the base: every firmware row belongs to one, and
    both of ADR 0007's gates need it. The repositories are plain attributes, which the read-only
    properties of the `FirmwareUnitOfWork` port accept. Projects' revisions come through a
    bootstrap subclass binding them to the same session (decision 5).
    """

    firmwares: SqlFirmwares
    versions: SqlVersions
    sources: SqlSources
    links: SqlRevisionLinks

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        workspace_id: WorkspaceId,
    ) -> None:
        super().__init__(session_factory, workspace_id)
        # Kept under its own name: the base holds a plain UUID, and the repositories speak
        # firmware's WorkspaceId.
        self._workspace = workspace_id

    async def __aenter__(self) -> Self:
        await super().__aenter__()
        self.firmwares = SqlFirmwares(self.session, self._workspace)
        self.versions = SqlVersions(self.session, self._workspace)
        self.sources = SqlSources(self.session, self._workspace)
        self.links = SqlRevisionLinks(self.session, self._workspace)
        return self

    async def clear(self) -> None:
        """Empty this workspace's firmware, for a demo bench being restored (ADR 0007).

        Each table is filtered on `workspace_id` itself, so it clears only this bench's rows
        even before the policies narrow it. The caller commits.
        """
        for table in _CLEAR_ORDER:
            await self.session.execute(delete(table).where(table.c.workspace_id == self._workspace))
