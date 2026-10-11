"""Minimum stock against Postgres (24-minimum-stock): the columns' round trip and CHECK, the
one read that finds the parts that may be watched, and a workspace's preferences kept apart
from another's by row-level security.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid7

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from wiredex.bootstrap.catalog import catalog_use_cases
from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.preferences import preferences_use_cases
from wiredex.bootstrap.settings import Environment, Settings
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
from wiredex.preferences.domain.preferences import StockBasis
from wiredex.preferences.domain.preferences import WorkspaceId as PreferencesWorkspaceId

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

NOW = datetime(2026, 10, 11, 10, tzinfo=UTC)
MINE = WorkspaceId(uuid7())
THEIRS = WorkspaceId(uuid7())
TABLES = "workspace_preferences, pins, part_definitions, attribute_definitions, categories"


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
    """The API's role and engine: row security applies."""
    settings = Settings(environment=Environment.TEST, database_url=SecretStr(app_database_url))
    engine = create_engine(settings)
    yield engine
    await engine.dispose()


def catalog(engine: AsyncEngine, workspace_id: WorkspaceId = MINE) -> SqlCatalogUnitOfWork:
    return SqlCatalogUnitOfWork(create_session_factory(engine), workspace_id)


def a_category(name: str, parent: Category | None = None, minimum: int | None = None) -> Category:
    return Category(
        CategoryId(uuid7()),
        MINE,
        None if parent is None else parent.id,
        CategoryName(name),
        NOW,
        minimum_stock=minimum,
    )


def a_part(category: Category, name: str, minimum: int | None = None) -> PartDefinition:
    details = PartDetails(PartName(name), minimum_stock=minimum)
    return PartDefinition.define(
        PartDefinitionId(uuid7()), category, details, AttributeValues(), NOW
    )


async def test_minimums_read_back_as_written_and_the_watched_parts_come_in_one_read(
    app: AsyncEngine,
) -> None:
    passives = a_category("Passives", minimum=20)
    resistors = a_category("Resistors", passives)
    hardware = a_category("Hardware")
    inherits = a_part(resistors, "R inherits")
    own = a_part(hardware, "Bolt own", minimum=100)
    opted_out = a_part(resistors, "R opted out", minimum=0)
    unwatched = a_part(hardware, "Bolt unwatched")
    gone = a_part(hardware, "Bolt gone", minimum=5)
    gone.move_to_trash(NOW)
    async with catalog(app) as work:
        for category in (passives, resistors, hardware):
            await work.categories.add(category)
        for part in (inherits, own, opted_out, unwatched, gone):
            await work.parts.add(part)
        await work.commit()

    async with catalog(app) as work:
        found = await work.categories.get(passives.id)
        watched = await work.parts.watched([passives.id, resistors.id])
        again = await work.parts.get(own.id)

    assert found is not None
    assert found.minimum_stock == 20
    assert again is not None
    assert again.minimum_stock == 100
    assert {part.name.value for part in watched} == {"R inherits", "Bolt own"}


async def test_the_database_refuses_a_minimum_out_of_range(admin: AsyncEngine) -> None:
    resistors = a_category("Resistors")
    async with catalog(admin) as work:
        await work.categories.add(resistors)
        await work.commit()

    for value in (-1, 1_000_001):
        with pytest.raises(IntegrityError, match="minimum_stock_range"):
            async with admin.begin() as connection:
                await connection.execute(
                    text("UPDATE categories SET minimum_stock = :value"), {"value": value}
                )


async def test_a_workspaces_choice_is_its_own_and_changes_what_its_list_compares_by(
    app: AsyncEngine,
) -> None:
    session_factory = create_session_factory(app)
    preferences = preferences_use_cases(session_factory)
    mine, theirs = PreferencesWorkspaceId(MINE), PreferencesWorkspaceId(THEIRS)

    assert (await preferences.get_preferences(mine)).stock_basis is StockBasis.FREE
    await preferences.update_preferences(mine, StockBasis.TOTAL)

    assert (await preferences.get_preferences(mine)).stock_basis is StockBasis.TOTAL
    assert (await preferences.get_preferences(theirs)).stock_basis is StockBasis.FREE
    # The list reads the choice through bootstrap, in the preferences' own transaction.
    reorder = await catalog_use_cases(session_factory).list_reorder(MINE)
    assert reorder.basis.value == "total"
    assert reorder.lines == []


async def test_another_workspaces_preferences_cant_be_read_or_written(
    app: AsyncEngine, admin: AsyncEngine
) -> None:
    preferences = preferences_use_cases(create_session_factory(app))
    await preferences.update_preferences(PreferencesWorkspaceId(MINE), StockBasis.TOTAL)

    async with app.begin() as connection:
        # No workspace named: row-level security shows nothing and refuses a write.
        rows = await connection.execute(text("SELECT count(*) FROM workspace_preferences"))
        assert rows.scalar_one() == 0
    with pytest.raises(Exception, match="row-level security"):
        async with app.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO workspace_preferences (workspace_id, stock_basis)"
                    " VALUES (:id, 'free')"
                ),
                {"id": uuid7()},
            )
    async with admin.connect() as connection:
        stored = await connection.execute(text("SELECT stock_basis FROM workspace_preferences"))
        assert [row[0] for row in stored] == ["total"]
