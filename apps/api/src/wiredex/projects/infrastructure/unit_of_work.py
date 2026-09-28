from collections.abc import Sequence
from typing import Self

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from wiredex.projects.application.ports import RevisionContent
from wiredex.projects.domain.values import WorkspaceId
from wiredex.projects.infrastructure.orm import projects, revisions
from wiredex.projects.infrastructure.repositories import SqlProjects, SqlRevisions
from wiredex.shared_kernel.infrastructure.unit_of_work import SqlUnitOfWork

# Deleted in foreign-key order for a demo reset: revisions point at projects. The cascade would
# take them anyway; naming them first keeps the order readable as the keys are.
_CLEAR_ORDER = (revisions, projects)


class SqlProjectsUnitOfWork(SqlUnitOfWork):
    """One transaction with the projects repositories bound to its session and workspace.

    The workspace is required here, unlike in the base: every projects row belongs to one, and
    both of ADR 0007's gates need it. The repositories are plain attributes, which the
    read-only properties of the `ProjectsUnitOfWork` port accept.

    `revision_contents` is what a fork copies, in order (decision 6). None here: 09 binds its
    BOM lines in `__aenter__` first and 11 its nets after, over this same session; another
    module's content comes through a bootstrap subclass binding its port to the session too.
    """

    projects: SqlProjects
    revisions: SqlRevisions
    revision_contents: Sequence[RevisionContent]

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        workspace_id: WorkspaceId,
    ) -> None:
        super().__init__(session_factory, workspace_id)
        # Kept under its own name: the base holds a plain UUID, and the repositories speak the
        # projects' WorkspaceId.
        self._workspace = workspace_id

    async def __aenter__(self) -> Self:
        await super().__aenter__()
        self.projects = SqlProjects(self.session, self._workspace)
        self.revisions = SqlRevisions(self.session, self._workspace)
        self.revision_contents = ()
        return self

    async def clear(self) -> None:
        """Empty this workspace's projects, for a demo bench being restored (ADR 0007).

        Each table is filtered on `workspace_id` itself, so it clears only this bench's rows
        even before the policies narrow it. The caller commits.
        """
        for table in _CLEAR_ORDER:
            await self.session.execute(delete(table).where(table.c.workspace_id == self._workspace))
