from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from wiredex.catalog.domain.values import WorkspaceId
from wiredex.catalog.infrastructure.repositories import (
    SqlAttributeDefinitions,
    SqlCategories,
    SqlPartDefinitions,
)
from wiredex.shared_kernel.infrastructure.unit_of_work import SqlUnitOfWork


class SqlCatalogUnitOfWork(SqlUnitOfWork):
    """One transaction with the catalog repositories bound to its session and workspace.

    The workspace is required here, unlike in the base: every catalog row belongs to one,
    and both of ADR 0007's gates need it — the repositories filter on it, and the base
    names it to Postgres so the policies on these tables apply.
    """

    categories: SqlCategories
    attribute_definitions: SqlAttributeDefinitions
    parts: SqlPartDefinitions

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
        self.categories = SqlCategories(self.session, self._workspace)
        self.attribute_definitions = SqlAttributeDefinitions(self.session, self._workspace)
        self.parts = SqlPartDefinitions(self.session, self._workspace)
        return self
