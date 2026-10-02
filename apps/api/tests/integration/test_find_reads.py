"""Each module's `find` over PostgreSQL, as `wiredex_app` (19-command-palette, decision 1).

What only the database can show: each find is one statement, the titles starting with the text
come first whatever collation the database has, `%`, `_` and `\\` match as typed, and a record in
the trash or of another bench is never answered, row-level security included.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID, uuid7

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from support.sql import counting
from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.settings import Environment, Settings
from wiredex.catalog.domain.category import Category
from wiredex.catalog.domain.part import PartDefinition, PartDetails
from wiredex.catalog.domain.schema import AttributeValues
from wiredex.catalog.domain.values import CategoryId, CategoryName, Mpn, PartDefinitionId, PartName
from wiredex.catalog.domain.values import Manufacturer as CatalogManufacturer
from wiredex.catalog.domain.values import WorkspaceId as CatalogWorkspaceId
from wiredex.catalog.infrastructure.unit_of_work import SqlCatalogUnitOfWork

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

NOW = datetime(2026, 10, 1, 9, tzinfo=UTC)
BENCH = uuid7()
OTHER = uuid7()
TABLES = (
    "pins, part_definitions, attribute_definitions, categories, history_entries, history_changes"
)


@pytest.fixture
async def admin(migrated_database_url: str) -> AsyncIterator[AsyncEngine]:
    """The schema owner, which the policies don't apply to: it sees every bench."""
    engine = create_async_engine(migrated_database_url)
    yield engine
    await engine.dispose()


@pytest.fixture(autouse=True)
async def clean(admin: AsyncEngine) -> AsyncIterator[None]:
    """Emptied by the owner afterwards: the app role is granted no TRUNCATE."""
    yield
    async with admin.begin() as connection:
        await connection.execute(text(f"TRUNCATE {TABLES} CASCADE"))


@pytest.fixture
async def app(app_database_url: str) -> AsyncIterator[AsyncEngine]:
    """The role the API logs in with, which row-level security applies to."""
    settings = Settings(environment=Environment.TEST, database_url=SecretStr(app_database_url))
    engine = create_engine(settings)
    yield engine
    await engine.dispose()


def catalog(app: AsyncEngine, workspace: UUID = BENCH) -> SqlCatalogUnitOfWork:
    return SqlCatalogUnitOfWork(create_session_factory(app), CatalogWorkspaceId(workspace))


async def a_category(app: AsyncEngine, name: str, workspace: UUID = BENCH) -> Category:
    category = Category(
        CategoryId(uuid7()), CatalogWorkspaceId(workspace), None, CategoryName(name), NOW
    )
    async with catalog(app, workspace) as work:
        await work.categories.add(category)
        await work.commit()
    return category


async def parts_in(
    app: AsyncEngine, category: Category, *named: str, mpn: str | None = None
) -> list[PartDefinition]:
    """Parts of the category, by name; the first one carries the MPN when one is given."""
    parts = [
        PartDefinition.define(
            PartDefinitionId(uuid7()),
            category,
            PartDetails(
                PartName(name),
                CatalogManufacturer("Yageo") if mpn and index == 0 else None,
                Mpn(mpn) if mpn and index == 0 else None,
            ),
            AttributeValues(),
            NOW,
        )
        for index, name in enumerate(named)
    ]
    async with catalog(app, category.workspace_id) as work:
        for part in parts:
            await work.parts.add(part)
        await work.commit()
    return parts


class TestCatalog:
    async def test_parts_are_found_in_one_statement_starting_ones_first(
        self, app: AsyncEngine
    ) -> None:
        # Requirements 1.1, 1.3 and 6.1: "res" starts two names, sorted by code point whatever
        # the database's collation ("Resistor" before "resonator"), then the one it is inside.
        passives = await a_category(app, "Passives")
        await parts_in(app, passives, "Pressure sensor", "resonator 16 MHz", "Resistor 10k")
        await parts_in(app, passives, "Thin film", mpn="RES-0805-1K")

        async with catalog(app) as work:
            with counting(app) as statements:
                found = await work.parts.find("res", 10)

        assert len(statements) == 1, statements
        assert [str(part.name) for part in found] == [
            "Resistor 10k",
            "resonator 16 MHz",
            "Pressure sensor",
            "Thin film",
        ]

    async def test_a_find_answers_at_most_its_limit(self, app: AsyncEngine) -> None:
        passives = await a_category(app, "Passives")
        await parts_in(app, passives, *(f"Resistor {index}" for index in range(5)))

        async with catalog(app) as work:
            found = await work.parts.find("resistor", 2)

        assert [str(part.name) for part in found] == ["Resistor 0", "Resistor 1"]

    async def test_wildcards_match_as_typed(self, app: AsyncEngine) -> None:
        # Requirement 1.6: `%`, `_` and `\` are characters, not patterns.
        passives = await a_category(app, "Passives")
        await parts_in(app, passives, "100% tested", "1000 ohm", "a_b", "axb", "back\\slash")

        async with catalog(app) as work:
            percent = await work.parts.find("100%", 10)
            underscore = await work.parts.find("a_b", 10)
            backslash = await work.parts.find("k\\s", 10)

        assert [str(part.name) for part in percent] == ["100% tested"]
        assert [str(part.name) for part in underscore] == ["a_b"]
        assert [str(part.name) for part in backslash] == ["back\\slash"]

    async def test_a_part_in_the_trash_or_of_another_bench_is_never_found(
        self, app: AsyncEngine
    ) -> None:
        # Requirements 2.1 and 2.2.
        passives = await a_category(app, "Passives")
        kept, trashed = await parts_in(app, passives, "Resistor 4k7", "Resistor 10k")
        async with catalog(app) as work:
            gone = await work.parts.get(trashed.id)
            assert gone is not None
            gone.move_to_trash(NOW)
            await work.commit()
        theirs = await a_category(app, "Passives", OTHER)
        await parts_in(app, theirs, "Resistor 1k")

        async with catalog(app) as work:
            found = await work.parts.find("resistor", 10)

        assert [part.id for part in found] == [kept.id]

    async def test_categories_are_found_in_one_statement_starting_ones_first(
        self, app: AsyncEngine
    ) -> None:
        for name in ("Passives", "Sensors", "Boards"):
            await a_category(app, name)
        await a_category(app, "Sensors", OTHER)

        async with catalog(app) as work:
            with counting(app) as statements:
                found = await work.categories.find("s", 10)

        assert len(statements) == 1, statements
        assert [str(category.name) for category in found] == ["Sensors", "Boards", "Passives"]
