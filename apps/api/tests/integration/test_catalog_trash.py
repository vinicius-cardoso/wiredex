"""Parts in the trash against a real PostgreSQL (16-soft-delete-and-trash, task 3).

What only the database can show: every read the repositories answer leaving a part in the trash
out, the MPN still held by the unique index, a page of the trash in one statement over its
partial index, the cascade taking the pins when a part is deleted for good, and a restore and a
delete for good of one part taking turns on its row.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
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
from wiredex.catalog.application.categories import UnitOfWorkFactory
from wiredex.catalog.application.ports import PartQuery
from wiredex.catalog.application.trash import DeletePartForGood, EmptyPartTrash, RestorePart
from wiredex.catalog.domain.category import Category
from wiredex.catalog.domain.errors import PartNotFoundError
from wiredex.catalog.domain.part import PartDefinition, PartDetails
from wiredex.catalog.domain.pinout import Pin, PinLabel, PinNumber, Pinout, PinType
from wiredex.catalog.domain.schema import AttributeDefinition, AttributeSchema, AttributeValues
from wiredex.catalog.domain.search import AllOf, PartSort, SortField
from wiredex.catalog.domain.values import (
    AttributeDefinitionId,
    AttributeKey,
    AttributeKind,
    AttributeLabel,
    CategoryId,
    CategoryName,
    Manufacturer,
    Mpn,
    PartDefinitionId,
    PartName,
    SiValue,
    Unit,
    WorkspaceId,
)
from wiredex.catalog.infrastructure.unit_of_work import SqlCatalogUnitOfWork
from wiredex.shared_kernel.domain.paging import PageRequest

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

NOW = datetime(2026, 10, 1, 9, tzinfo=UTC)
BENCH = WorkspaceId(uuid7())
RESISTANCE = AttributeKey("resistance")


@pytest.fixture
async def engine(migrated_database_url: str) -> AsyncIterator[AsyncEngine]:
    settings = Settings(environment=Environment.TEST, database_url=SecretStr(migrated_database_url))
    engine = create_engine(settings)
    yield engine
    async with engine.begin() as connection:
        await connection.execute(
            text("TRUNCATE pins, part_definitions, attribute_definitions, categories CASCADE")
        )
    await engine.dispose()


def catalog(engine: AsyncEngine) -> SqlCatalogUnitOfWork:
    return SqlCatalogUnitOfWork(create_session_factory(engine), BENCH)


def factory(engine: AsyncEngine) -> UnitOfWorkFactory:
    sessions = create_session_factory(engine)
    return lambda workspace_id: SqlCatalogUnitOfWork(sessions, workspace_id)


@dataclass(frozen=True, slots=True)
class Bench:
    resistors: Category
    resistance: AttributeDefinition

    def a_resistor(self, name: str, mpn: str | None = None, ohms: int = 4700) -> PartDefinition:
        details = PartDetails(
            PartName(name),
            None if mpn is None else Manufacturer("Yageo"),
            None if mpn is None else Mpn(mpn),
        )
        values = AttributeValues({RESISTANCE: SiValue(Decimal(ohms))})
        return PartDefinition.define(
            PartDefinitionId(uuid7()), self.resistors, details, values, NOW
        )


async def a_bench(engine: AsyncEngine) -> Bench:
    resistors = Category(CategoryId(uuid7()), BENCH, None, CategoryName("Resistors"), NOW)
    resistance = AttributeDefinition(
        AttributeDefinitionId(uuid7()),
        BENCH,
        resistors.id,
        RESISTANCE,
        AttributeLabel("Resistance"),
        AttributeKind.NUMBER,
        Unit("Ω"),
        True,
    )
    async with catalog(engine) as work:
        await work.categories.add(resistors)
        await work.attribute_definitions.add(resistance)
        await work.commit()
    return Bench(resistors, resistance)


async def store(engine: AsyncEngine, *parts: PartDefinition, trashed: int = 0) -> None:
    """The parts, the first `trashed` of them moved to the trash a minute apart, in order."""
    async with catalog(engine) as work:
        for part in parts:
            await work.parts.add(part)
        await work.commit()
    async with catalog(engine) as work:
        for minutes, part in enumerate(parts[:trashed], start=1):
            found = await work.parts.locked(part.id)
            assert found is not None
            found.move_to_trash(NOW + timedelta(minutes=minutes))
        await work.commit()


async def test_a_part_in_the_trash_is_absent_from_every_read(engine: AsyncEngine) -> None:
    bench = await a_bench(engine)
    gone = bench.a_resistor("R 4k7", "RC0805FR-074K7L")
    kept = bench.a_resistor("R 10k", ohms=10_000)
    await store(engine, gone, kept, trashed=1)
    schema = AttributeSchema((bench.resistance,))

    async with catalog(engine) as work:
        assert await work.parts.get(gone.id) is None
        assert await work.parts.locked(gone.id) is None
        assert [part.id for part in await work.parts.with_ids([gone.id, kept.id])] == [kept.id]
        listed = await work.parts.listed(PartQuery(), PageRequest())
        assert [part.id for part in listed] == [kept.id]
        assert await work.parts.count_listed(PartQuery()) == 1
        found = await work.parts.search(AllOf(()), PartSort(SortField.NEWEST), PageRequest(1, 10))
        assert [part.id for part in found] == [kept.id]
        assert await work.parts.count_matching(AllOf(())) == 1
        facets = await work.parts.facets(AllOf(()), schema)
        resistances = facets.numbers[RESISTANCE]
        assert resistances is not None
        assert (resistances.minimum, resistances.maximum) == (SiValue(Decimal(10_000)),) * 2
        assert await work.parts.counts_by_category() == {bench.resistors.id: 1}
        assert await work.parts.count_in([bench.resistors.id]) == 1
        assert await work.parts.count_in_trash([bench.resistors.id]) == 1
        # The MPN is still held, and the check finds its holder (16's decision 5).
        holder = await work.parts.with_mpn(Manufacturer("YAGEO"), Mpn("rc0805fr-074k7l"))
        assert holder is not None
        assert holder.id == gone.id


async def test_the_unique_index_keeps_a_trashed_parts_mpn(engine: AsyncEngine) -> None:
    bench = await a_bench(engine)
    await store(engine, bench.a_resistor("R 4k7", "RC0805FR-074K7L"), trashed=1)
    again = bench.a_resistor("R 4k7, again", "rc0805fr-074k7l")

    async with catalog(engine) as work:
        await work.parts.add(again)
        with pytest.raises(IntegrityError, match="uq_part_definitions_mpn"):
            await work.commit()


async def test_the_trash_is_read_newest_first_with_its_total_in_one_statement(
    engine: AsyncEngine,
) -> None:
    bench = await a_bench(engine)
    parts = [bench.a_resistor(f"R {ohms}", ohms=ohms) for ohms in (100, 220, 330, 470)]
    await store(engine, *parts, trashed=3)

    async with catalog(engine) as work:
        with counting(engine) as statements:
            first = await work.parts.trashed(2, None)
        assert [part.id for part in first.items] == [parts[2].id, parts[1].id]
        assert first.total == 3
        assert len(statements) == 1
        everything = await work.parts.trashed(10, None)
        assert [part.id for part in everything.items] == [p.id for p in reversed(parts[:3])]
        assert everything.total == 3


async def test_a_text_narrows_the_trash_by_name_or_mpn_its_wildcards_as_characters(
    engine: AsyncEngine,
) -> None:
    bench = await a_bench(engine)
    by_name = bench.a_resistor("R 4k7 1% 0805")
    by_mpn = bench.a_resistor("R 1k", "RC0805FR-071KL", ohms=1000)
    neither = bench.a_resistor("R 220", "RC0603", ohms=220)
    live = bench.a_resistor("R 4k7 1% 0603")
    await store(engine, by_name, by_mpn, neither, live, trashed=3)

    async with catalog(engine) as work:
        with counting(engine) as statements:
            percent = await work.parts.trashed(10, "1%")
        assert [part.id for part in percent.items] == [by_name.id]
        assert len(statements) == 1
        either = await work.parts.trashed(1, "0805")
        assert ([part.id for part in either.items], either.total) == ([by_mpn.id], 2)
        assert [p.id for p in (await work.parts.trashed(10, "fr-07")).items] == [by_mpn.id]
        assert (await work.parts.trashed(10, "R_4")).total == 0


async def test_the_parts_named_are_the_live_ones_whose_name_holds_the_text(
    engine: AsyncEngine,
) -> None:
    bench = await a_bench(engine)
    trashed = bench.a_resistor("R 4k7 spare")
    live = bench.a_resistor("R 4k7 0805")
    other = bench.a_resistor("R 1k", ohms=1000)
    await store(engine, trashed, live, other, trashed=1)

    async with catalog(engine) as work:
        with counting(engine) as statements:
            named = await work.parts.ids_named("r 4K7")
        assert named == frozenset({live.id})
        assert len(statements) == 1
        assert await work.parts.ids_named("4_7") == frozenset()


async def test_a_part_deleted_for_good_takes_its_pins(engine: AsyncEngine) -> None:
    bench = await a_bench(engine)
    part = bench.a_resistor("BME280")
    await store(engine, part)
    async with catalog(engine) as work:
        await work.pinouts.replace(
            part.id, Pinout([Pin(PinNumber("1"), PinLabel("VDD"), PinType.POWER)])
        )
        found = await work.parts.locked(part.id)
        assert found is not None
        found.move_to_trash(NOW)
        await work.commit()

    await DeletePartForGood(factory(engine))(BENCH, part.id)

    async with engine.connect() as connection:
        left = await connection.scalar(text("SELECT count(*) FROM pins"))
        parts = await connection.scalar(text("SELECT count(*) FROM part_definitions"))
    assert (left, parts) == (0, 0)


async def test_emptying_the_trash_keeps_the_live_parts(engine: AsyncEngine) -> None:
    bench = await a_bench(engine)
    parts = [bench.a_resistor(f"R {ohms}", ohms=ohms) for ohms in (100, 220, 330)]
    await store(engine, *parts, trashed=2)

    assert await EmptyPartTrash(factory(engine))(BENCH) == 2

    async with catalog(engine) as work:
        assert (await work.parts.trashed(10, None)).total == 0
        assert [p.id for p in await work.parts.listed(PartQuery(), PageRequest())] == [parts[2].id]


async def test_a_restored_part_comes_back_as_it_was(engine: AsyncEngine) -> None:
    bench = await a_bench(engine)
    part = bench.a_resistor("R 4k7", "RC0805FR-074K7L")
    await store(engine, part, trashed=1)

    await RestorePart(factory(engine))(BENCH, part.id)

    async with catalog(engine) as work:
        found = await work.parts.get(part.id)
        assert found is not None
        assert found.details == part.details
        assert found.trashed_at is None
        assert found.updated_at == NOW


@asynccontextmanager
async def part_held(engine: AsyncEngine, part_id: PartDefinitionId) -> AsyncIterator[None]:
    """The part's row locked by an outside transaction until the block ends, so the two
    requests line up on it before either reads the part."""
    async with engine.begin() as holder:
        await holder.execute(
            text("SELECT id FROM part_definitions WHERE id = :id FOR UPDATE"), {"id": part_id}
        )
        yield


async def until_waiting(engine: AsyncEngine, count: int) -> None:
    for _ in range(200):
        async with engine.connect() as watcher:
            waiting = await watcher.scalar(
                text("SELECT count(*) FROM pg_stat_activity WHERE wait_event_type = 'Lock'")
            )
        if (waiting or 0) >= count:
            return
        await asyncio.sleep(0.05)
    pytest.fail(f"expected {count} transactions waiting for the part's lock")


async def test_a_restore_and_a_delete_for_good_of_one_part_take_turns(
    engine: AsyncEngine,
) -> None:
    # Requirement 5.4: without the lock both would find the part in the trash, and the delete
    # would take the part the restore had just brought back.
    bench = await a_bench(engine)
    part = bench.a_resistor("R 4k7")
    await store(engine, part, trashed=1)
    work = factory(engine)

    async with part_held(engine, part.id):
        racing = [
            asyncio.create_task(RestorePart(work)(BENCH, part.id)),
            asyncio.create_task(DeletePartForGood(work)(BENCH, part.id)),
        ]
        await until_waiting(engine, 2)
    outcomes = await asyncio.gather(*racing, return_exceptions=True)

    assert outcomes.count(None) == 1
    assert len([o for o in outcomes if isinstance(o, PartNotFoundError)]) == 1
    async with engine.connect() as connection:
        rows = [
            tuple(row)
            for row in await connection.execute(text("SELECT trashed_at FROM part_definitions"))
        ]
    # Restored and still there, or deleted for good and gone: never both.
    assert rows in ([(None,)], [])
