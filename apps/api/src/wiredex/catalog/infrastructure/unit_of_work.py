from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from wiredex.catalog.domain.values import WorkspaceId
from wiredex.catalog.infrastructure.repositories import (
    SqlAttributeDefinitions,
    SqlCategories,
    SqlPartDefinitions,
    SqlPinouts,
)
from wiredex.shared_kernel.infrastructure.unit_of_work import SqlUnitOfWork


class SqlCatalogRepositories:
    """The four catalog repositories bound to a session, which may be someone else's.

    The catalog's own unit of work builds its repositories through this. So does the
    composition root, over the session inventory's intake opened, so a part and its first
    stock are written in one transaction (design decision 2). Nothing here opens, commits or
    scopes a transaction: whoever opened the session did, and every query still filters on
    `workspace_id` itself, ADR 0007's first gate.
    """

    categories: SqlCategories
    attribute_definitions: SqlAttributeDefinitions
    parts: SqlPartDefinitions
    pinouts: SqlPinouts

    def __init__(self, session: AsyncSession, workspace_id: WorkspaceId) -> None:
        self.categories = SqlCategories(session, workspace_id)
        self.attribute_definitions = SqlAttributeDefinitions(session, workspace_id)
        self.parts = SqlPartDefinitions(session, workspace_id)
        self.pinouts = SqlPinouts(session, workspace_id)


class SqlCatalogUnitOfWork(SqlUnitOfWork):
    """One transaction with the catalog repositories bound to its session and workspace.

    The workspace is required here, unlike in the base: every catalog row belongs to one,
    and both of ADR 0007's gates need it — the repositories filter on it, and the base
    names it to Postgres so the policies on these tables apply.
    """

    categories: SqlCategories
    attribute_definitions: SqlAttributeDefinitions
    parts: SqlPartDefinitions
    pinouts: SqlPinouts

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        workspace_id: WorkspaceId,
    ) -> None:
        super().__init__(session_factory, workspace_id)
        # Kept under its own name: the base holds a plain UUID, and the repositories speak
        # the catalog's WorkspaceId.
        self._workspace = workspace_id

    async def __aenter__(self) -> Self:
        await super().__aenter__()
        repositories = SqlCatalogRepositories(self.session, self._workspace)
        self.categories = repositories.categories
        self.attribute_definitions = repositories.attribute_definitions
        self.parts = repositories.parts
        self.pinouts = repositories.pinouts
        return self
