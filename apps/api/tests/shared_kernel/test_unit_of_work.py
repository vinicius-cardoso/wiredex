import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from wiredex.shared_kernel.infrastructure.unit_of_work import SqlUnitOfWork


def test_the_session_only_exists_inside_the_block() -> None:
    # Creating an engine doesn't connect, so no database is needed here.
    engine = create_async_engine("postgresql+asyncpg://unused@localhost/unused")
    uow = SqlUnitOfWork(async_sessionmaker(engine))

    with pytest.raises(RuntimeError, match="inside `async with`"):
        _ = uow.session
