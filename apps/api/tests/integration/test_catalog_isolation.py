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
from sqlalchemy import insert, text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.settings import Environment, Settings
from wiredex.catalog.application.ports import PartQuery
from wiredex.catalog.domain.category import Category
from wiredex.catalog.domain.part import PartDefinition, PartDetails
from wiredex.catalog.domain.pinout import Pinout, PinType, RawPin
from wiredex.catalog.domain.schema import AttributeDefinition, AttributeValues
from wiredex.catalog.domain.search import (
    AllOf,
    InCategories,
    PartSort,
    SearchText,
    TextContains,
)
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
from wiredex.catalog.infrastructure.orm import pins
from wiredex.catalog.infrastructure.unit_of_work import SqlCatalogUnitOfWork

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

NOW = datetime(2026, 9, 25, 10, tzinfo=UTC)
MINE = WorkspaceId(uuid7())
THEIRS = WorkspaceId(uuid7())
CATALOG_TABLES = "pins, part_definitions, attribute_definitions, categories"
A_PINOUT = Pinout.parse(
    [
        RawPin(number="1", label="GND", type="ground"),
        RawPin(number="8", label="VDD", type="power", voltage="3V3"),
    ]
)


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


async def seed_my_pinout(engine: AsyncEngine, part: PartDefinition) -> None:
    async with catalog(engine, MINE) as work:
        await work.pinouts.replace(part.id, A_PINOUT)
        await work.commit()


async def part_names(engine: AsyncEngine) -> list[str]:
    async with engine.connect() as connection:
        rows = await connection.execute(text("SELECT name FROM part_definitions ORDER BY name"))
        return list(rows.scalars())


async def pin_labels(engine: AsyncEngine) -> list[str]:
    """Every pin in the table, read by the owner: what the policies were holding back."""
    async with engine.connect() as connection:
        rows = await connection.execute(text("SELECT label FROM pins ORDER BY position"))
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


async def test_my_pins_are_mine_to_read(app: AsyncEngine) -> None:
    # Requirement 4.1, the half that has to keep working: my own bench is readable.
    _, _, part = await seed_my_bench(app)
    await seed_my_pinout(app, part)

    async with catalog(app, MINE) as work:
        assert await work.pinouts.of_part(part.id) == A_PINOUT
        assert await work.pinouts.count_of(part.id) == 2


async def test_another_workspace_sees_none_of_my_pins(app: AsyncEngine) -> None:
    # Requirement 4.1: pins are as private as the part they hang off, and by the same gate.
    _, _, part = await seed_my_bench(app)
    await seed_my_pinout(app, part)

    async with catalog(app, THEIRS) as work:
        assert await work.pinouts.of_part(part.id) == Pinout.empty()
        assert await work.pinouts.count_of(part.id) == 0
        # Without any filter either: the policy, not the repository, is what hides them.
        assert await work.session.scalar(text("SELECT count(*) FROM pins")) == 0


async def test_another_workspace_cannot_touch_my_pins(app: AsyncEngine, admin: AsyncEngine) -> None:
    # Requirement 4.1 for writes: statements with no WHERE at all, and my table is untouched.
    # Read back as the owner, the one role that sees every workspace's rows.
    _, _, part = await seed_my_bench(app)
    await seed_my_pinout(app, part)

    async with catalog(app, THEIRS) as work:
        await work.session.execute(text("UPDATE pins SET label = 'Stolen'"))
        await work.session.execute(text("DELETE FROM pins"))
        await work.commit()

    assert await pin_labels(admin) == ["GND", "VDD"]


async def test_another_workspace_cannot_file_a_pin_under_my_part(
    app: AsyncEngine, admin: AsyncEngine
) -> None:
    """Requirement 4.2: the composite foreign key, which no policy is needed for.

    Their transaction, their `workspace_id` on the row — so the policy's WITH CHECK is happy —
    but pointing at my part. The pair `(workspace_id, part_id)` matches no part of theirs, and
    the database refuses it: the gate that holds even when the application asks wrongly.
    """
    _, _, part = await seed_my_bench(app)

    async with catalog(app, THEIRS) as work:
        with pytest.raises(IntegrityError, match="fk_pins_workspace_id_part_definitions"):
            await work.pinouts.replace(part.id, A_PINOUT)

    assert await pin_labels(admin) == []


async def test_even_the_owner_cannot_split_a_pin_from_its_part(admin: AsyncEngine) -> None:
    """Requirement 4.2 without row-level security in the way at all.

    The schema owner is the one role the policies don't apply to, which is why the rule lives
    in a constraint: a pin whose `workspace_id` isn't its part's is refused here too.
    """
    resistors = Category(CategoryId(uuid7()), MINE, None, CategoryName("Resistors"), NOW)
    part = PartDefinition.define(
        PartDefinitionId(uuid7()),
        resistors,
        PartDetails(PartName("R 4k7 0805")),
        AttributeValues(),
        NOW,
    )
    async with catalog(admin, MINE) as work:
        await work.categories.add(resistors)
        await work.parts.add(part)
        await work.commit()

    planted = insert(pins).values(
        workspace_id=THEIRS,
        part_id=part.id,
        position=0,
        number="1",
        label="Planted",
        type=PinType.GROUND,
    )

    with pytest.raises(IntegrityError, match="fk_pins_workspace_id_part_definitions"):
        async with admin.begin() as connection:
            await connection.execute(planted)

    assert await pin_labels(admin) == []


async def seed_their_bench(engine: AsyncEngine) -> PartDefinition:
    """A category and a part in the other workspace, its name matching a search I'll run."""
    resistors = Category(CategoryId(uuid7()), THEIRS, None, CategoryName("Resistors"), NOW)
    part = PartDefinition.define(
        PartDefinitionId(uuid7()),
        resistors,
        PartDetails(PartName("R 4k7 0805")),
        AttributeValues(),
        NOW,
    )
    async with catalog(engine, THEIRS) as work:
        await work.categories.add(resistors)
        await work.parts.add(part)
        await work.commit()
    return part


async def test_a_search_never_returns_another_workspaces_parts(app: AsyncEngine) -> None:
    """A parametric search as `wiredex_app` sees only the caller's parts (ADR 0007).

    Both workspaces hold an "R 4k7 0805", so a text search that would match either returns
    only mine when run as me and only theirs when run as them — the row-security gate under
    the compiled `WHERE`, not the workspace filter the repository also adds.
    """
    _, _, mine = await seed_my_bench(app)
    theirs = await seed_their_bench(app)
    spec = AllOf((TextContains(SearchText("4k7")),))

    async with catalog(app, MINE) as work:
        my_page = await work.parts.search(spec, PartSort.newest(), None, limit=50)
    async with catalog(app, THEIRS) as work:
        their_page = await work.parts.search(spec, PartSort.newest(), None, limit=50)

    assert [part.id for part in my_page.items] == [mine.id]
    assert [part.id for part in their_page.items] == [theirs.id]


async def test_a_search_without_a_category_stays_within_the_workspace(app: AsyncEngine) -> None:
    """Requirement 1.4 under isolation: "every part" is every part of *my* workspace.

    An empty-of-text search over a category set that names my category returns my part; the
    other workspace, asked for the same category id, sees nothing — the id isn't its own.
    """
    resistors, _, mine = await seed_my_bench(app)
    await seed_their_bench(app)
    spec = AllOf((InCategories(frozenset({resistors.id})),))

    async with catalog(app, MINE) as work:
        my_page = await work.parts.search(spec, PartSort.newest(), None, limit=50)
    async with catalog(app, THEIRS) as work:
        their_page = await work.parts.search(spec, PartSort.newest(), None, limit=50)

    assert [part.id for part in my_page.items] == [mine.id]
    assert their_page.items == ()
