from types import TracebackType
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class SqlUnitOfWork:
    """UnitOfWork over one AsyncSession.

    Leaving the `async with` block without `commit()` rolls everything back, including
    when an exception escapes. Each module subclasses this to expose its repositories.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None

    @property
    def session(self) -> AsyncSession:
        if self._session is None:
            raise RuntimeError("use the unit of work inside `async with`")
        return self._session

    async def __aenter__(self) -> Self:
        self._session = self._session_factory()
        await self._session.begin()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        session = self.session
        try:
            await session.rollback()  # a no-op after commit()
        finally:
            await session.close()
            self._session = None

    async def commit(self) -> None:
        await self.session.commit()
