from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from wiredex.shared_kernel.infrastructure.unit_of_work import SqlUnitOfWork

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.execute(text("DROP TABLE IF EXISTS uow_probe"))
        await connection.execute(text("CREATE TABLE uow_probe (note text)"))
    yield engine
    async with engine.begin() as connection:
        await connection.execute(text("DROP TABLE uow_probe"))
    await engine.dispose()


def unit_of_work(engine: AsyncEngine) -> SqlUnitOfWork:
    return SqlUnitOfWork(async_sessionmaker(engine, class_=AsyncSession))


async def notes(engine: AsyncEngine) -> list[str]:
    async with engine.connect() as connection:
        rows = await connection.execute(text("SELECT note FROM uow_probe ORDER BY note"))
        return [row.note for row in rows]


async def insert(uow: SqlUnitOfWork, note: str) -> None:
    await uow.session.execute(text("INSERT INTO uow_probe VALUES (:note)"), {"note": note})


async def test_commit_keeps_the_changes(engine: AsyncEngine) -> None:
    async with unit_of_work(engine) as uow:
        await insert(uow, "kept")
        await uow.commit()

    assert await notes(engine) == ["kept"]


async def test_leaving_without_commit_rolls_back(engine: AsyncEngine) -> None:
    async with unit_of_work(engine) as uow:
        await insert(uow, "forgotten")

    assert await notes(engine) == []


async def failing_use_case(engine: AsyncEngine) -> None:
    async with unit_of_work(engine) as uow:
        await insert(uow, "failed")
        raise RuntimeError("the use case failed")


async def test_an_exception_rolls_back(engine: AsyncEngine) -> None:
    with pytest.raises(RuntimeError):
        await failing_use_case(engine)

    assert await notes(engine) == []
