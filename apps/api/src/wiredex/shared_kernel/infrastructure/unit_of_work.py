from types import TracebackType
from typing import Self
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from wiredex.shared_kernel.infrastructure.row_security import scope_to_workspace


class SqlUnitOfWork:
    """UnitOfWork over one AsyncSession.

    Leaving the `async with` block without `commit()` discards everything, including
    when an exception escapes. Each module subclasses this to expose its repositories.

    With a `workspace_id`, row-level security limits the transaction to that
    workspace's rows. Without one, workspace-isolated tables look empty and refuse
    writes; tables outside any workspace, like users, are unaffected.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        workspace_id: UUID | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._workspace_id = workspace_id
        self._session: AsyncSession | None = None

    @property
    def session(self) -> AsyncSession:
        if self._session is None:
            raise RuntimeError("use the unit of work inside `async with`")
        return self._session

    async def __aenter__(self) -> Self:
        self._session = self._session_factory()
        await self._session.begin()
        if self._workspace_id is not None:
            await scope_to_workspace(self._session, self._workspace_id)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        # close() discards anything not committed. Unlike rollback(), it leaves the
        # objects already loaded readable, so a read-only use case can return them.
        await self.session.close()
        self._session = None

    async def commit(self) -> None:
        await self.session.commit()
