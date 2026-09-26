"""The catalog repositories against a real PostgreSQL: the tree, the indexes, the numbers.

What can only be checked here is what the database does: one recursive query for a whole
ancestor chain, the constraints that refuse a duplicate root or a folded MPN, and a
`Decimal` coming back exactly as it went in.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid7

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from support.sql import counting
from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.settings import Environment, Settings
from wiredex.catalog.application.ports import CatalogUnitOfWork, PartQuery
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
    Manufacturer,
    Mpn,
    Package,
    PartDefinitionId,
    PartName,
    SiValue,
    Unit,
    WorkspaceId,
)
from wiredex.catalog.infrastructure.unit_of_work import SqlCatalogUnitOfWork

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

NOW = datetime(2026, 9, 25, 10, tzinfo=UTC)
BENCH = WorkspaceId(uuid7())
OHM = Unit("Ω")
CATALOG_TABLES = "part_definitions, attribute_definitions, categories"


@pytest.fixture
async def engine(migrated_database_url: str) -> AsyncIterator[AsyncEngine]:
    # The engine the API builds, not a bare one: its JSON serializer is what keeps a
    # Decimal exact all the way into JSONB (ADR 0005).
    settings = Settings(environment=Environment.TEST, database_url=SecretStr(migrated_database_url))
    engine = create_engine(settings)
    yield engine
    async with engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE {CATALOG_TABLES} CASCADE"))
    await engine.dispose()


def catalog(engine: AsyncEngine, workspace_id: WorkspaceId = BENCH) -> SqlCatalogUnitOfWork:
    return SqlCatalogUnitOfWork(create_session_factory(engine), workspace_id)


def a_category(name: str, parent: Category | None = None) -> Category:
    return Category(
        CategoryId(uuid7()),
        BENCH,
        None if parent is None else parent.id,
        CategoryName(name),
        NOW,
    )


def a_part(
    category: Category,
    name: str = "R 4k7 0805",
    details: PartDetails | None = None,
    attributes: AttributeValues | None = None,
) -> PartDefinition:
    return PartDefinition.define(
        PartDefinitionId(uuid7()),
        category,
        PartDetails(PartName(name)) if details is None else details,
        AttributeValues() if attributes is None else attributes,
        NOW,
    )


async def save(engine: AsyncEngine, *rows: Category | AttributeDefinition | PartDefinition) -> None:
    """Seeds straight through the repositories, parents first: the FKs want them in order."""
    async with catalog(engine) as work:
        for row in rows:
            match row:
                case Category():
                    await work.categories.add(row)
                case AttributeDefinition():
                    await work.attribute_definitions.add(row)
                case PartDefinition():
                    await work.parts.add(row)
        await work.commit()


async def test_the_unit_of_work_binds_the_catalog_repositories(engine: AsyncEngine) -> None:
    # Typed as the port the use cases take, so the real unit of work is checked against it.
    work: CatalogUnitOfWork = catalog(engine)

    async with work as opened:
        assert await opened.categories.all() == []
        assert await opened.attribute_definitions.of_categories([]) == []
        assert await opened.parts.counts_by_category() == {}


async def test_the_ancestor_chain_comes_root_first_in_one_query(engine: AsyncEngine) -> None:
    passives = a_category("Passives")
    resistors = a_category("Resistors", passives)
    thick_film = a_category("Thick film", resistors)
    await save(engine, passives, resistors, thick_film)

    async with catalog(engine) as work:
        with counting(engine) as statements:
            chain = await work.categories.ancestors(thick_film.id)

    assert [str(category.name) for category in chain] == ["Passives", "Resistors"]
    assert len(statements) == 1, statements


async def test_a_categorys_descendants_are_the_whole_subtree_in_one_query(
    engine: AsyncEngine,
) -> None:
    # A three-level tree: the root, a branch, and a leaf under the branch.
    passives = a_category("Passives")
    resistors = a_category("Resistors", passives)
    thick_film = a_category("Thick film", resistors)
    await save(engine, passives, resistors, thick_film)

    async with catalog(engine) as work:
        with counting(engine) as statements:
            subtree = await work.categories.descendants(passives.id)
        leaf = await work.categories.descendants(thick_film.id)

    # The root pulls its whole subtree, itself included; a leaf pulls only itself.
    assert set(subtree) == {passives.id, resistors.id, thick_film.id}
    assert leaf == [thick_film.id]
    assert len(statements) == 1, statements


async def test_another_workspaces_subtree_is_never_returned(engine: AsyncEngine) -> None:
    # Two workspaces, each with its own tree. Descendants filters workspace_id itself, so
    # the other bench's categories stay unseen even under the same root call (ADR 0007).
    other = WorkspaceId(uuid7())
    mine_root = a_category("Passives")
    mine_child = a_category("Resistors", mine_root)
    theirs_root = Category(CategoryId(uuid7()), other, None, CategoryName("Passives"), NOW)
    theirs_child = Category(CategoryId(uuid7()), other, theirs_root.id, CategoryName("R"), NOW)
    await save(engine, mine_root, mine_child)
    async with catalog(engine, other) as work:
        await work.categories.add(theirs_root)
        await work.categories.add(theirs_child)
        await work.commit()

    async with catalog(engine) as work:
        subtree = await work.categories.descendants(mine_root.id)

    assert set(subtree) == {mine_root.id, mine_child.id}


async def test_a_root_has_no_ancestors(engine: AsyncEngine) -> None:
    passives = a_category("Passives")
    await save(engine, passives)

    async with catalog(engine) as work:
        assert await work.categories.ancestors(passives.id) == []


async def test_the_tree_is_read_by_parent_and_by_sibling_name(engine: AsyncEngine) -> None:
    passives = a_category("Passives")
    resistors = a_category("Resistors", passives)
    await save(engine, passives, resistors)

    async with catalog(engine) as work:
        children = await work.categories.children_of(passives.id)
        taken = await work.categories.sibling_named(passives.id, CategoryName("Resistors"))
        free = await work.categories.sibling_named(passives.id, CategoryName("Capacitors"))
        # Roots are siblings of each other, which no parent id can express.
        root = await work.categories.sibling_named(None, CategoryName("Passives"))

    assert [child.id for child in children] == [resistors.id]
    assert taken is not None
    assert taken.id == resistors.id
    assert free is None
    assert root is not None
    assert root.id == passives.id


async def test_a_second_root_with_the_same_name_is_refused(engine: AsyncEngine) -> None:
    # NULLS NOT DISTINCT: without it Postgres would take two parentless Passives rows for
    # different siblings and store both (requirement 1.3).
    with pytest.raises(IntegrityError, match="uq_categories_workspace_id"):
        await save(engine, a_category("Passives"), a_category("Passives"))


async def test_a_definition_is_read_back_with_its_unit_and_options(engine: AsyncEngine) -> None:
    resistors = a_category("Resistors")
    resistance = AttributeDefinition(
        AttributeDefinitionId(uuid7()),
        BENCH,
        resistors.id,
        AttributeKey("resistance"),
        AttributeLabel("Resistance"),
        AttributeKind.NUMBER,
        OHM,
        required=True,
    )
    tolerance = AttributeDefinition(
        AttributeDefinitionId(uuid7()),
        BENCH,
        resistors.id,
        AttributeKey("tolerance"),
        AttributeLabel("Tolerance"),
        AttributeKind.ENUM,
        options=("1%", "5%"),
        position=1,
    )
    await save(engine, resistors, resistance, tolerance)

    async with catalog(engine) as work:
        defined = await work.attribute_definitions.of_categories([resistors.id])
        one = await work.attribute_definitions.get(resistance.id)

    assert [str(definition.key) for definition in defined] == ["resistance", "tolerance"]
    assert one is not None
    assert (one.unit, one.kind, one.required) == (OHM, AttributeKind.NUMBER, True)
    # A tuple, as the domain declares it, not the JSON list it was stored as.
    assert defined[1].options == ("1%", "5%")


async def test_an_exact_number_survives_the_round_trip(engine: AsyncEngine) -> None:
    resistors = a_category("Resistors")
    stored = AttributeValues(
        {
            AttributeKey("resistance"): SiValue(Decimal("4.7E+3")),
            AttributeKey("capacitance"): SiValue(Decimal("1E-7")),  # 100n
            AttributeKey("tolerance"): "1%",
            AttributeKey("rohs"): True,
        }
    )
    part = a_part(resistors, attributes=stored)
    await save(engine, resistors, part)

    async with catalog(engine) as work:
        read = await work.parts.get(part.id)

    assert read is not None
    assert read.attributes == stored
    # SiValue again, not the Decimal the column holds: a revision that changes nothing has
    # to compare equal to what the schema just validated (requirement 4.9).
    assert read.attributes[AttributeKey("resistance")] == SiValue(Decimal("4700"))
    assert read.revise(read.details, stored, NOW) is False


async def test_the_same_mpn_in_another_case_is_refused(engine: AsyncEngine) -> None:
    resistors = a_category("Resistors")
    first = a_part(resistors, details=_bme280("TI", "BME280"))
    second = a_part(resistors, details=_bme280("ti", "bme280"))

    with pytest.raises(IntegrityError, match="uq_part_definitions_mpn"):
        await save(engine, resistors, first, second)


async def test_two_parts_with_the_same_bare_mpn_are_refused(engine: AsyncEngine) -> None:
    # A missing manufacturer folds to the empty string, so these two collide; as NULL it
    # would never collide and both would be stored (design §5).
    resistors = a_category("Resistors")
    first = a_part(resistors, details=PartDetails(PartName("Sensor"), mpn=Mpn("BME280")))
    second = a_part(resistors, details=PartDetails(PartName("Other"), mpn=Mpn("bme280")))

    with pytest.raises(IntegrityError, match="uq_part_definitions_mpn"):
        await save(engine, resistors, first, second)


async def test_any_number_of_parts_without_an_mpn_is_fine(engine: AsyncEngine) -> None:
    resistors = a_category("Resistors")
    await save(engine, resistors, a_part(resistors, "One"), a_part(resistors, "Another"))

    async with catalog(engine) as work:
        assert await work.parts.count_in([resistors.id]) == 2


async def test_a_part_is_found_by_its_folded_mpn(engine: AsyncEngine) -> None:
    resistors = a_category("Resistors")
    sensor = a_part(resistors, details=_bme280("TI", "BME280"))
    bare = a_part(resistors, details=PartDetails(PartName("Bare"), mpn=Mpn("LM358")))
    await save(engine, resistors, sensor, bare)

    async with catalog(engine) as work:
        found = await work.parts.with_mpn(Manufacturer("ti"), Mpn("bme280"))
        # No manufacturer searched the same way the index folds it.
        found_bare = await work.parts.with_mpn(None, Mpn("lm358"))
        other = await work.parts.with_mpn(Manufacturer("Bosch"), Mpn("BME280"))

    assert found is not None
    assert found.id == sensor.id
    assert found_bare is not None
    assert found_bare.id == bare.id
    assert other is None


async def test_a_page_stops_at_its_limit_and_carries_a_cursor(engine: AsyncEngine) -> None:
    resistors = a_category("Resistors")
    capacitors = a_category("Capacitors")
    first, second, third = (a_part(resistors, f"R {n}") for n in ("4k7", "10k", "100k"))
    fourth = a_part(capacitors, "C 100n")
    await save(engine, resistors, capacitors, first, second, third, fourth)

    async with catalog(engine) as work:
        page = await work.parts.page(PartQuery(limit=2))
        assert page.next_cursor is not None
        carry_on = PartQuery(limit=2, after=PartDefinitionId(page.next_cursor))
        rest = await work.parts.page(carry_on)
        searched = await work.parts.page(PartQuery(text="100"))
        in_category = await work.parts.page(PartQuery(category_id=capacitors.id))

    # Ordered by id, which for UUIDv7 is the order they were defined in.
    assert [part.id for part in page.items] == [first.id, second.id]
    assert page.next_cursor == second.id
    assert [part.id for part in rest.items] == [third.id, fourth.id]
    # The last window carries no cursor: there is nothing after it (design §4).
    assert rest.next_cursor is None
    assert sorted(str(part.name) for part in searched.items) == ["C 100n", "R 100k"]
    assert [str(part.name) for part in in_category.items] == ["C 100n"]


async def test_a_search_takes_a_wildcard_as_a_character(engine: AsyncEngine) -> None:
    resistors = a_category("Resistors")
    await save(engine, resistors, a_part(resistors, "R 4k7 5%"), a_part(resistors, "R 10k 1%"))

    async with catalog(engine) as work:
        page = await work.parts.page(PartQuery(text="5%"))

    assert [str(part.name) for part in page.items] == ["R 4k7 5%"]


async def test_parts_are_counted_by_category(engine: AsyncEngine) -> None:
    resistors = a_category("Resistors")
    capacitors = a_category("Capacitors")
    empty = a_category("Inductors")
    parts = (a_part(resistors, "R 4k7"), a_part(resistors, "R 10k"), a_part(capacitors, "C 100n"))
    await save(engine, resistors, capacitors, empty, *parts)

    async with catalog(engine) as work:
        counts = await work.parts.counts_by_category()
        in_both = await work.parts.count_in([resistors.id, capacitors.id])

    assert counts == {resistors.id: 2, capacitors.id: 1}
    assert in_both == 3


async def test_what_is_removed_is_gone(engine: AsyncEngine) -> None:
    resistors = a_category("Resistors")
    part = a_part(resistors)
    await save(engine, resistors, part)

    async with catalog(engine) as work:
        stored = await work.parts.get(part.id)
        assert stored is not None
        await work.parts.remove(stored)
        await work.commit()

    async with catalog(engine) as work:
        assert await work.parts.get(part.id) is None
        assert await work.parts.count_in([resistors.id]) == 0


async def test_a_category_goes_with_its_definitions_but_never_with_its_parts(
    engine: AsyncEngine,
) -> None:
    resistors = a_category("Resistors")
    resistance = AttributeDefinition(
        AttributeDefinitionId(uuid7()),
        BENCH,
        resistors.id,
        AttributeKey("resistance"),
        AttributeLabel("Resistance"),
        AttributeKind.NUMBER,
        OHM,
    )
    await save(engine, resistors, resistance, a_part(resistors))

    # RESTRICT is the backstop under DeleteCategory's refusal: a part still points here.
    async with catalog(engine) as work:
        doomed = await work.categories.get(resistors.id)
        assert doomed is not None
        await work.categories.remove(doomed)
        with pytest.raises(IntegrityError, match="fk_part_definitions_category_id_categories"):
            await work.commit()

    async with catalog(engine) as work:
        for part in (await work.parts.page(PartQuery())).items:
            await work.parts.remove(part)
        for definition in await work.attribute_definitions.of_categories([resistors.id]):
            await work.attribute_definitions.remove(definition)
        emptied = await work.categories.get(resistors.id)
        assert emptied is not None
        await work.categories.remove(emptied)
        await work.commit()

    async with catalog(engine) as work:
        assert await work.categories.all() == []
        assert await work.attribute_definitions.get(resistance.id) is None


def _bme280(manufacturer: str, mpn: str) -> PartDetails:
    return PartDetails(
        PartName("BME280 sensor"),
        Manufacturer(manufacturer),
        Mpn(mpn),
        Package("LGA-8"),
    )
