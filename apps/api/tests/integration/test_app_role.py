from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


@pytest.fixture
async def app(app_database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(app_database_url)
    yield engine
    await engine.dispose()


@pytest.fixture
async def admin(migrated_database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(migrated_database_url)
    yield engine
    await engine.dispose()


async def execute(engine: AsyncEngine, sql: str) -> None:
    async with engine.begin() as connection:
        await connection.execute(text(sql))


async def test_the_app_role_reads_and_writes_rows(app: AsyncEngine) -> None:
    async with app.connect() as connection:
        await connection.execute(
            text(
                "INSERT INTO workspaces (id, name, kind, created_at)"
                " VALUES (gen_random_uuid(), 'Probe', 'personal', now())"
            )
        )
        await connection.execute(text("UPDATE workspaces SET name = 'Renamed'"))
        deleted = await connection.execute(text("DELETE FROM workspaces RETURNING id"))
        await connection.rollback()

    assert len(deleted.all()) == 1


async def test_the_app_role_is_not_exempt_from_row_security(app: AsyncEngine) -> None:
    async with app.connect() as connection:
        rows = await connection.execute(
            text(
                "SELECT rolsuper, rolbypassrls, rolcreatedb, rolcreaterole"
                " FROM pg_roles WHERE rolname = current_user"
            )
        )

    assert rows.one() == (False, False, False, False)


async def test_the_app_role_cannot_change_the_schema(app: AsyncEngine) -> None:
    with pytest.raises(ProgrammingError, match="permission denied"):
        await execute(app, "CREATE TABLE intruder (id int)")

    with pytest.raises(ProgrammingError, match="must be owner"):
        await execute(app, "ALTER TABLE users DISABLE ROW LEVEL SECURITY")


async def test_the_app_role_cannot_see_the_schema_version(app: AsyncEngine) -> None:
    with pytest.raises(ProgrammingError, match="permission denied"):
        await execute(app, "SELECT * FROM alembic_version")


async def test_tables_from_later_migrations_are_granted_too(
    admin: AsyncEngine, app: AsyncEngine
) -> None:
    await execute(admin, "CREATE TABLE later_table (note text)")
    try:
        await execute(app, "INSERT INTO later_table VALUES ('granted')")
    finally:
        await execute(admin, "DROP TABLE later_table")
