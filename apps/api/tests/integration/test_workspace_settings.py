"""The workspace's settings against Postgres (25-workspace-settings): every choice saved and
read back, the CHECKs that hold them, and the purge that keeps a trash for a number of days.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid7

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.preferences import code_prefix_of, preferences_use_cases
from wiredex.bootstrap.settings import Environment, Settings
from wiredex.bootstrap.trash import trash_bins
from wiredex.catalog.domain.category import Category
from wiredex.catalog.domain.part import PartDefinition, PartDetails
from wiredex.catalog.domain.schema import AttributeValues
from wiredex.catalog.domain.values import (
    CategoryId,
    CategoryName,
    PartDefinitionId,
    PartName,
    WorkspaceId,
)
from wiredex.catalog.infrastructure.unit_of_work import SqlCatalogUnitOfWork
from wiredex.preferences.domain.preferences import (
    Choices,
    DateFormat,
    NumberFormat,
    StockBasis,
)
from wiredex.preferences.domain.preferences import WorkspaceId as PreferencesWorkspaceId
from wiredex.trash.application.trash import PurgeTrash
from wiredex.trash.domain.values import WorkspaceId as TrashWorkspaceId

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

NOW = datetime(2026, 10, 11, 10, tzinfo=UTC)
MINE = WorkspaceId(uuid7())
TABLES = "workspace_preferences, pins, part_definitions, attribute_definitions, categories"


class FixedClock:
    def now(self) -> datetime:
        return NOW


@pytest.fixture
async def admin(migrated_database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(migrated_database_url)
    yield engine
    async with engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE {TABLES} CASCADE"))
    await engine.dispose()


@pytest.fixture
async def app(
    app_database_url: str,
    admin: AsyncEngine,  # noqa: ARG001  the owner empties the tables once the test ends
) -> AsyncIterator[AsyncEngine]:
    settings = Settings(environment=Environment.TEST, database_url=SecretStr(app_database_url))
    engine = create_engine(settings)
    yield engine
    await engine.dispose()


async def test_every_choice_is_saved_and_read_back(app: AsyncEngine) -> None:
    session_factory = create_session_factory(app)
    preferences = preferences_use_cases(session_factory)
    chosen = Choices(
        stock_basis=StockBasis.TOTAL,
        default_minimum_stock=5,
        code_prefix="lab2",
        date_format=DateFormat.ISO,
        number_format=NumberFormat.COMMA,
        trash_retention_days=30,
    )

    await preferences.update_preferences(PreferencesWorkspaceId(MINE), chosen)

    read = await preferences.get_preferences(PreferencesWorkspaceId(MINE))
    assert read.choices == chosen
    assert read.code_prefix == "LAB2"
    assert await code_prefix_of(session_factory)(MINE) == "LAB2"


async def test_the_database_refuses_a_choice_out_of_shape(admin: AsyncEngine) -> None:
    async with admin.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO workspace_preferences (workspace_id, stock_basis) VALUES (:id, 'free')"
            ),
            {"id": MINE},
        )
    for column, value in [
        ("code_prefix", "'wx'"),
        ("code_prefix", "'1AB'"),
        ("date_format", "'yyyy'"),
        ("number_format", "'space'"),
        ("default_minimum_stock", "-1"),
        ("trash_retention_days", "0"),
    ]:
        # The column and the literal come from the list above, never from input.
        statement = text(f"UPDATE workspace_preferences SET {column} = {value}")  # noqa: S608
        with pytest.raises(IntegrityError):
            async with admin.begin() as connection:
                await connection.execute(statement)


async def test_a_row_the_previous_release_inserts_takes_the_defaults(admin: AsyncEngine) -> None:
    # The release before 0029 inserts the stock basis alone.
    async with admin.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO workspace_preferences (workspace_id, stock_basis) VALUES (:id, 'free')"
            ),
            {"id": MINE},
        )
        row = (
            await connection.execute(
                text("SELECT code_prefix, date_format, number_format FROM workspace_preferences")
            )
        ).one()
    assert tuple(row) == ("WX", "language", "language")


async def test_the_purge_deletes_for_good_only_what_is_past_the_days(app: AsyncEngine) -> None:
    category = Category(CategoryId(uuid7()), MINE, None, CategoryName("Resistors"), NOW)
    old, recent, live = (
        PartDefinition.define(
            PartDefinitionId(uuid7()), category, PartDetails(PartName(name)), AttributeValues(), NOW
        )
        for name in ("R old", "R recent", "R live")
    )
    old.move_to_trash(NOW - timedelta(days=40))
    recent.move_to_trash(NOW - timedelta(days=3))
    session_factory = create_session_factory(app)
    async with SqlCatalogUnitOfWork(session_factory, MINE) as work:
        await work.categories.add(category)
        for part in (old, recent, live):
            await work.parts.add(part)
        await work.commit()

    await PurgeTrash(trash_bins(session_factory), FixedClock())(TrashWorkspaceId(MINE), 30)

    async with SqlCatalogUnitOfWork(session_factory, MINE) as work:
        kept = {
            part.name.value
            for part in await work.parts.with_ids([p.id for p in (old, recent, live)])
        }
        recent_kept = await work.parts.kept(recent.id)
        old_kept = await work.parts.kept(old.id)
    assert kept == {"R live"}
    assert recent_kept
    assert not old_kept
