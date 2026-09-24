"""Row-level security, proven on a scratch table shaped like a workspace's data."""

from collections.abc import AsyncIterator
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from wiredex.shared_kernel.infrastructure.row_security import isolate_by_workspace
from wiredex.shared_kernel.infrastructure.unit_of_work import SqlUnitOfWork

# Every test needs the scratch table, which the owner's fixture creates.
pytestmark = [pytest.mark.integration, pytest.mark.anyio, pytest.mark.usefixtures("admin")]

MINE = UUID("00000000-0000-7000-8000-00000000000a")
THEIRS = UUID("00000000-0000-7000-8000-00000000000b")


@pytest.fixture
async def admin(migrated_database_url: str) -> AsyncIterator[AsyncEngine]:
    """The schema owner: creates the table, like a migration would."""
    engine = create_async_engine(migrated_database_url)
    statements: list[str] = []
    isolate_by_workspace(statements.append, "rls_probe")
    async with engine.begin() as connection:
        await connection.execute(
            text("CREATE TABLE rls_probe (workspace_id uuid NOT NULL, label text NOT NULL)")
        )
        for statement in statements:
            await connection.exec_driver_sql(statement)
        await connection.execute(
            text("INSERT INTO rls_probe VALUES (:mine, 'mine'), (:theirs, 'theirs')"),
            {"mine": MINE, "theirs": THEIRS},
        )
    yield engine
    async with engine.begin() as connection:
        await connection.execute(text("DROP TABLE rls_probe"))
    await engine.dispose()


@pytest.fixture
async def app(app_database_url: str) -> AsyncIterator[AsyncEngine]:
    """The API's role. One pooled connection, so every test reuses the same session."""
    engine = create_async_engine(app_database_url, pool_size=1, max_overflow=0)
    yield engine
    await engine.dispose()


def unit_of_work(engine: AsyncEngine, workspace_id: UUID | None) -> SqlUnitOfWork:
    return SqlUnitOfWork(async_sessionmaker(engine, class_=AsyncSession), workspace_id)


async def labels(uow: SqlUnitOfWork) -> list[str]:
    rows = await uow.session.execute(text("SELECT label FROM rls_probe ORDER BY label"))
    return list(rows.scalars())


async def test_a_workspace_sees_only_its_own_rows(app: AsyncEngine) -> None:
    async with unit_of_work(app, MINE) as uow:
        assert await labels(uow) == ["mine"]


async def test_without_a_workspace_nothing_is_visible(app: AsyncEngine) -> None:
    async with unit_of_work(app, None) as uow:
        assert await labels(uow) == []


async def test_a_query_without_a_filter_cannot_change_another_workspace(
    app: AsyncEngine, admin: AsyncEngine
) -> None:
    async with unit_of_work(app, MINE) as uow:
        await uow.session.execute(text("UPDATE rls_probe SET label = 'changed'"))
        await uow.session.execute(text("DELETE FROM rls_probe WHERE label = 'theirs'"))
        await uow.commit()

    assert await all_labels(admin) == ["changed", "theirs"]


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO rls_probe VALUES (:theirs, 'planted')",
        "UPDATE rls_probe SET workspace_id = :theirs",
    ],
    ids=["insert", "move"],
)
async def test_rows_cannot_be_written_into_another_workspace(
    app: AsyncEngine, statement: str
) -> None:
    async with unit_of_work(app, MINE) as uow:
        with pytest.raises(ProgrammingError, match="row-level security"):
            await uow.session.execute(text(statement), {"theirs": THEIRS})


async def test_the_workspace_lasts_only_for_its_transaction(app: AsyncEngine) -> None:
    async with unit_of_work(app, MINE) as uow:
        await uow.commit()

    # The same pooled connection, in a new transaction: the workspace is gone.
    async with unit_of_work(app, None) as uow:
        assert await labels(uow) == []


async def test_the_schema_owner_sees_every_workspace(admin: AsyncEngine) -> None:
    assert await all_labels(admin) == ["mine", "theirs"]


async def all_labels(engine: AsyncEngine) -> list[str]:
    async with engine.connect() as connection:
        rows = await connection.execute(text("SELECT label FROM rls_probe ORDER BY label"))
        return list(rows.scalars())
