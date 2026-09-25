"""Workspace isolation over the catalog tables, as the role the API logs in with.

The repositories filter `workspace_id` themselves, but that is a promise the code makes.
This is the gate underneath it (ADR 0007): as `wiredex_app`, another workspace's catalog
isn't there to be read, written or moved, filter or no filter.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid7

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.settings import Environment, Settings
from wiredex.catalog.application.ports import PartQuery
from wiredex.catalog.domain.category import Category
from wiredex.catalog.domain.part import PartDefinition, PartDetails
from wiredex.catalog.domain.schema import AttributeDefinition, AttributeValues
from wiredex.catalog.domain.values import (
    AttributeDefinitionId,
    AttributeKey,
    AttributeKind,
    AttributeLabel,
    CategoryId,
    CategoryName,
    PartDefinitionId,
    PartName,
    SiValue,
    Unit,
    WorkspaceId,
)
from wiredex.catalog.infrastructure.unit_of_work import SqlCatalogUnitOfWork

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

NOW = datetime(2026, 9, 25, 10, tzinfo=UTC)
MINE = WorkspaceId(uuid7())
THEIRS = WorkspaceId(uuid7())
CATALOG_TABLES = "part_definitions, attribute_definitions, categories"


@pytest.fixture
async def admin(migrated_database_url: str) -> AsyncIterator[AsyncEngine]:
    """The schema owner, which the policies don't apply to: it sees every workspace."""
    engine = create_async_engine(migrated_database_url)
    yield engine
    await engine.dispose()


@pytest.fixture(autouse=True)
async def clean(admin: AsyncEngine) -> AsyncIterator[None]:
    """Emptied by the owner afterwards: the app role is granted no TRUNCATE."""
    yield
    async with admin.begin() as connection:
        await connection.execute(text(f"TRUNCATE {CATALOG_TABLES} CASCADE"))


@pytest.fixture
async def app(app_database_url: str) -> AsyncIterator[AsyncEngine]:
    """The API's role, with the API's engine: row security applies, and Decimals stay exact."""
    settings = Settings(environment=Environment.TEST, database_url=SecretStr(app_database_url))
    engine = create_engine(settings)
    yield engine
    await engine.dispose()


def catalog(engine: AsyncEngine, workspace_id: WorkspaceId) -> SqlCatalogUnitOfWork:
    return SqlCatalogUnitOfWork(create_session_factory(engine), workspace_id)


async def seed_my_bench(
    engine: AsyncEngine,
) -> tuple[Category, AttributeDefinition, PartDefinition]:
    """One category, one attribute and one part, all of them mine."""
    resistors = Category(CategoryId(uuid7()), MINE, None, CategoryName("Resistors"), NOW)
    resistance = AttributeDefinition(
        AttributeDefinitionId(uuid7()),
        MINE,
        resistors.id,
        AttributeKey("resistance"),
        AttributeLabel("Resistance"),
        AttributeKind.NUMBER,
        Unit("Ω"),
        required=True,
    )
    part = PartDefinition.define(
        PartDefinitionId(uuid7()),
        resistors,
        PartDetails(PartName("R 4k7 0805")),
        AttributeValues({AttributeKey("resistance"): SiValue(Decimal("4700"))}),
        NOW,
    )
    async with catalog(engine, MINE) as work:
        await work.categories.add(resistors)
        await work.attribute_definitions.add(resistance)
        await work.parts.add(part)
        await work.commit()
    return resistors, resistance, part


async def part_names(engine: AsyncEngine) -> list[str]:
    async with engine.connect() as connection:
        rows = await connection.execute(text("SELECT name FROM part_definitions ORDER BY name"))
        return list(rows.scalars())


async def test_my_own_bench_is_readable(app: AsyncEngine) -> None:
    resistors, resistance, part = await seed_my_bench(app)

    async with catalog(app, MINE) as work:
        assert [category.id for category in await work.categories.all()] == [resistors.id]
        defined = await work.attribute_definitions.of_categories([resistors.id])
        assert [definition.id for definition in defined] == [resistance.id]
        found = await work.parts.get(part.id)

    assert found is not None
    assert found.attributes[AttributeKey("resistance")] == SiValue(Decimal("4700"))


async def test_another_workspace_sees_none_of_it(app: AsyncEngine) -> None:
    resistors, _, part = await seed_my_bench(app)

    async with catalog(app, THEIRS) as work:
        assert await work.categories.all() == []
        # By id, so this is requirement 6.4 too: another workspace's id is simply not found.
        assert await work.categories.get(resistors.id) is None
        assert await work.attribute_definitions.of_categories([resistors.id]) == []
        assert await work.parts.get(part.id) is None
        assert (await work.parts.page(PartQuery())).items == ()
        assert await work.parts.counts_by_category() == {}


async def test_a_part_cannot_be_written_into_another_workspace(app: AsyncEngine) -> None:
    resistors, _, _ = await seed_my_bench(app)
    planted = PartDefinition.define(
        PartDefinitionId(uuid7()),
        resistors,  # carries my workspace, while the transaction is theirs
        PartDetails(PartName("Planted")),
        AttributeValues(),
        NOW,
    )

    async with catalog(app, THEIRS) as work:
        await work.parts.add(planted)
        with pytest.raises(ProgrammingError, match="row-level security"):
            await work.commit()


async def test_a_write_without_a_filter_cannot_touch_another_workspace(
    app: AsyncEngine, admin: AsyncEngine
) -> None:
    await seed_my_bench(app)

    async with catalog(app, THEIRS) as work:
        # No WHERE at all: the policy is what keeps these from reaching my rows.
        await work.session.execute(text("UPDATE part_definitions SET name = 'Stolen'"))
        await work.session.execute(text("DELETE FROM part_definitions"))
        await work.session.execute(text("DELETE FROM categories"))
        await work.commit()

    assert await part_names(admin) == ["R 4k7 0805"]


async def test_a_read_without_a_filter_sees_one_workspace(app: AsyncEngine) -> None:
    await seed_my_bench(app)

    async with catalog(app, THEIRS) as work:
        theirs = await work.session.scalar(text("SELECT count(*) FROM part_definitions"))

    async with catalog(app, MINE) as work:
        mine = await work.session.scalar(text("SELECT count(*) FROM part_definitions"))

    assert (theirs, mine) == (0, 1)
