from collections.abc import Sequence
from typing import Self

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from wiredex.projects.application.bom import CopyBomLines
from wiredex.projects.application.netlist import CopyNetlist
from wiredex.projects.application.ports import RevisionContent
from wiredex.projects.domain.values import WorkspaceId
from wiredex.projects.infrastructure.orm import (
    bom_designators,
    bom_lines,
    net_pins,
    nets,
    projects,
    revisions,
)
from wiredex.projects.infrastructure.repositories import (
    SqlBomLines,
    SqlNets,
    SqlProjects,
    SqlRevisions,
)
from wiredex.shared_kernel.application.ports import IdGenerator
from wiredex.shared_kernel.infrastructure.unit_of_work import SqlUnitOfWork

# Deleted in foreign-key order for a demo reset: references point at nets, designators at
# lines, nets and lines at revisions, revisions at projects. The cascades would take them
# anyway; naming them keeps the order readable as the keys are.
_CLEAR_ORDER = (net_pins, nets, bom_designators, bom_lines, revisions, projects)


class SqlProjectsUnitOfWork(SqlUnitOfWork):
    """One transaction with the projects repositories bound to its session and workspace.

    The workspace is required here, unlike in the base: every projects row belongs to one, and
    both of ADR 0007's gates need it. The repositories are plain attributes, which the
    read-only properties of the `ProjectsUnitOfWork` port accept.

    `revision_contents` is what a fork copies, in order (08's decision 6): the BOM first, bound
    to this session with the ids its copies are minted from (09's decision 15), and 11's nets
    after it (11's decision 10); another module's content comes through a bootstrap subclass
    binding its port to the session too. Binding `bom_lines` makes it a `BomUnitOfWork` as well.
    """

    projects: SqlProjects
    revisions: SqlRevisions
    bom_lines: SqlBomLines
    nets: SqlNets
    revision_contents: Sequence[RevisionContent]

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        workspace_id: WorkspaceId,
        ids: IdGenerator,
    ) -> None:
        super().__init__(session_factory, workspace_id)
        # Kept under its own name: the base holds a plain UUID, and the repositories speak the
        # projects' WorkspaceId.
        self._workspace = workspace_id
        self._ids = ids

    async def __aenter__(self) -> Self:
        await super().__aenter__()
        self.projects = SqlProjects(self.session, self._workspace)
        self.revisions = SqlRevisions(self.session, self._workspace)
        self.bom_lines = SqlBomLines(self.session, self._workspace)
        self.nets = SqlNets(self.session, self._workspace)
        self.revision_contents = (
            CopyBomLines(self.bom_lines, self._ids),
            CopyNetlist(self.nets, self._ids),
        )
        return self

    async def clear(self) -> None:
        """Empty this workspace's projects, for a demo bench being restored (ADR 0007).

        Each table is filtered on `workspace_id` itself, so it clears only this bench's rows
        even before the policies narrow it. The caller commits.
        """
        for table in _CLEAR_ORDER:
            await self.session.execute(delete(table).where(table.c.workspace_id == self._workspace))
