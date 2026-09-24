from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from wiredex.bootstrap.settings import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    """One engine per process. The pool stays small: production has under 1 GB of RAM."""
    return create_async_engine(
        settings.database_url.get_secret_value(),
        pool_size=5,
        max_overflow=5,
        pool_pre_ping=True,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    # expire_on_commit=False: objects stay readable after commit, for building responses.
    return async_sessionmaker(engine, expire_on_commit=False)
