"""`SqlPinouts` against a real PostgreSQL: the order, the cost, the cascade, the exact volts.

What only the database can answer. A `Pinout` is not a mapped entity, so nothing here is the
session's doing: the repository turns rows into pins and pins into rows itself, and these
tests are what say it does so faithfully — same pins, same order, same `Decimal`.

Two of them count statements instead of reading rows. A pinout of forty pins has to cost one
query to read and two statements to replace (requirements 7.1 and 7.2), and a repository that
loops over the pins would pass every other test in this file.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid7

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from support.sql import counting
from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.settings import Environment, Settings
from wiredex.catalog.domain.category import Category
from wiredex.catalog.domain.part import PartDefinition, PartDetails
from wiredex.catalog.domain.pinout import Pinout, RawPin
from wiredex.catalog.domain.schema import AttributeValues
from wiredex.catalog.domain.values import (
    CategoryId,
    CategoryName,
    PartDefinitionId,
    PartName,
    WorkspaceId,
)
from wiredex.catalog.infrastructure.unit_of_work import SqlCatalogUnitOfWork

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

NOW = datetime(2026, 9, 25, 10, tzinfo=UTC)
BENCH = WorkspaceId(uuid7())
CATALOG_TABLES = "pins, part_definitions, attribute_definitions, categories"

# The BME280 of design.md's demo bench, four of its eight pins: alternate functions on one,
# two pins at 3V3, two labelled GND, and numbers that skip, because a pin table is read in
# the order it was typed and never sorted.
BME280_ROWS = (
    RawPin(number="1", label="GND", type="ground"),
    RawPin(number="3", label="SDI", type="io", functions=("SDA", "MOSI"), voltage="3V3"),
    RawPin(number="4", label="SCK", type="io", functions=("SCL",), voltage="3V3"),
    RawPin(number="7", label="GND", type="ground"),
)
# A board's worth of pins, for the tests that are about cost rather than content.
A_BIG_BOARD = tuple(RawPin(number=str(pin), label=f"P{pin}", type="io") for pin in range(1, 41))


@pytest.fixture
async def engine(migrated_database_url: str) -> AsyncIterator[AsyncEngine]:
    # The API's engine, as the other repository tests use it: its JSON and numeric handling
    # is part of what keeps a voltage exact.
    settings = Settings(environment=Environment.TEST, database_url=SecretStr(migrated_database_url))
    engine = create_engine(settings)
    yield engine
    async with engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE {CATALOG_TABLES} CASCADE"))
    await engine.dispose()


@pytest.fixture
async def sensor(engine: AsyncEngine) -> PartDefinition:
    """One part in one category: a pinout is always some part's, and which part is no matter."""
    sensors = Category(CategoryId(uuid7()), BENCH, None, CategoryName("Sensors"), NOW)
    part = PartDefinition.define(
        PartDefinitionId(uuid7()),
        sensors,
        PartDetails(PartName("BME280")),
        AttributeValues(),
        NOW,
    )
    async with catalog(engine) as work:
        await work.categories.add(sensors)
        await work.parts.add(part)
        await work.commit()
    return part


def catalog(engine: AsyncEngine, workspace_id: WorkspaceId = BENCH) -> SqlCatalogUnitOfWork:
    return SqlCatalogUnitOfWork(create_session_factory(engine), workspace_id)


async def store(engine: AsyncEngine, part: PartDefinition, pinout: Pinout) -> None:
    async with catalog(engine) as work:
        await work.pinouts.replace(part.id, pinout)
        await work.commit()


async def read(engine: AsyncEngine, part: PartDefinition) -> Pinout:
    async with catalog(engine) as work:
        return await work.pinouts.of_part(part.id)


async def stored_rows(engine: AsyncEngine) -> int:
    """Every row of `pins`, filter or no filter: what is really left in the table."""
    async with engine.connect() as connection:
        return await connection.scalar(text("SELECT count(*) FROM pins")) or 0


async def test_a_pinout_comes_back_whole_and_in_the_order_it_was_saved(
    engine: AsyncEngine, sensor: PartDefinition
) -> None:
    # Requirement 1.1: position is stored because the datasheet's order is information.
    await store(engine, sensor, Pinout.parse(BME280_ROWS))

    read_back = await read(engine, sensor)

    assert read_back == Pinout.parse(BME280_ROWS)
    assert [str(pin.number) for pin in read_back] == ["1", "3", "4", "7"]
    # Two GND labels, which numbers may never be but labels are (requirement 2.5).
    assert [str(pin.label) for pin in read_back] == ["GND", "SDI", "SCK", "GND"]
    sdi = list(read_back)[1]
    assert [str(function) for function in sdi.functions] == ["SDA", "MOSI"]
    assert str(sdi.type) == "io"


async def test_a_part_with_no_pins_reads_as_an_empty_pinout(
    engine: AsyncEngine, sensor: PartDefinition
) -> None:
    # Requirement 1.2, over the real table: no row is not a missing part.
    async with catalog(engine) as work:
        assert await work.pinouts.of_part(sensor.id) == Pinout.empty()
        assert await work.pinouts.count_of(sensor.id) == 0


async def test_a_replace_leaves_nothing_of_the_old_table(
    engine: AsyncEngine, sensor: PartDefinition
) -> None:
    """Requirement 1.3: the whole table is replaced, so no pin can outlive its pinout.

    The numbers don't overlap on purpose: a repository that updated rows by number, instead of
    deleting them all, would leave the four old pins behind and still answer with the new two.
    """
    await store(engine, sensor, Pinout.parse(BME280_ROWS))
    shorter = Pinout.parse(
        [
            RawPin(number="A1", label="VDD", type="power", voltage="3V3"),
            RawPin(number="A2", label="VSS", type="ground"),
        ]
    )

    await store(engine, sensor, shorter)

    assert await read(engine, sensor) == shorter
    assert await stored_rows(engine) == 2


async def test_an_empty_replace_clears_the_table(
    engine: AsyncEngine, sensor: PartDefinition
) -> None:
    # Requirement 1.4: a pinout entered by mistake is taken back by saving no pins.
    await store(engine, sensor, Pinout.parse(BME280_ROWS))

    await store(engine, sensor, Pinout.empty())

    assert await read(engine, sensor) == Pinout.empty()
    assert await stored_rows(engine) == 0


@pytest.mark.parametrize(
    ("typed", "volts"),
    [
        pytest.param("3V3", Decimal("3.3"), id="the board convention"),
        pytest.param("1V8", Decimal("1.8"), id="another one"),
        pytest.param("5", Decimal(5), id="a whole number"),
        pytest.param("-12V", Decimal(-12), id="a negative rail"),
        pytest.param("500mV", Decimal("0.5"), id="millivolts, in volts"),
    ],
)
async def test_a_voltage_survives_the_round_trip_exactly(
    engine: AsyncEngine, sensor: PartDefinition, typed: str, volts: Decimal
) -> None:
    # Requirement 2.9 through a numeric column: no float gets to make 3.3 into 3.2999999.
    await store(
        engine, sensor, Pinout.parse([RawPin(number="1", label="VDD", type="power", voltage=typed)])
    )

    pin = next(iter(await read(engine, sensor)))

    assert pin.voltage is not None
    assert pin.voltage.value == volts
    assert str(pin.voltage) == f"{volts:f}"


async def test_a_pin_without_a_voltage_reads_back_without_one(
    engine: AsyncEngine, sensor: PartDefinition
) -> None:
    # Requirement 2.11: most pins have no level, and a NULL column is exactly that.
    await store(engine, sensor, Pinout.parse([RawPin(number="1", label="NC", type="nc")]))

    assert next(iter(await read(engine, sensor))).voltage is None


async def test_deleting_the_part_deletes_its_pins(
    engine: AsyncEngine, sensor: PartDefinition
) -> None:
    """Requirement 1.7, through the composite foreign key's ON DELETE CASCADE.

    Nothing in the application deletes a pin, so this is the only thing that does: rows really
    gone from the table, not rows a filter no longer reaches.
    """
    await store(engine, sensor, Pinout.parse(BME280_ROWS))

    async with catalog(engine) as work:
        stored = await work.parts.get(sensor.id)
        assert stored is not None
        await work.parts.remove(stored)
        await work.commit()

    assert await stored_rows(engine) == 0


async def test_a_pinout_is_written_for_a_part_defined_in_the_same_transaction(
    engine: AsyncEngine,
) -> None:
    """What restoring a demo bench does: define a part and write its pins in one unit of work.

    The part is still pending in the session at that point, and a Core statement doesn't flush
    it the way an ORM one would, so the composite foreign key would refuse its pins. `replace`
    flushes first, which is what makes a sample pinout possible at all (requirement 4.3).
    """
    boards = Category(CategoryId(uuid7()), BENCH, None, CategoryName("Boards"), NOW)
    fresh = PartDefinition.define(
        PartDefinitionId(uuid7()),
        boards,
        PartDetails(PartName("BME280 breakout")),
        AttributeValues(),
        NOW,
    )

    async with catalog(engine) as work:
        await work.categories.add(boards)
        await work.parts.add(fresh)
        await work.pinouts.replace(fresh.id, Pinout.parse(BME280_ROWS))
        await work.commit()

    assert await read(engine, fresh) == Pinout.parse(BME280_ROWS)


async def test_reading_a_pinout_is_one_query_whatever_the_pin_count(
    engine: AsyncEngine, sensor: PartDefinition
) -> None:
    # Requirement 7.1: a forty-pin board costs a part page no more than a resistor does.
    await store(engine, sensor, Pinout.parse(A_BIG_BOARD))

    async with catalog(engine) as work:
        with counting(engine) as statements:
            read_back = await work.pinouts.of_part(sensor.id)

    assert len(read_back) == len(A_BIG_BOARD)
    assert len(statements) == 1, statements


async def test_counting_the_pins_is_one_query_and_reads_none_of_them(
    engine: AsyncEngine, sensor: PartDefinition
) -> None:
    # What `PartView.pin_count` costs (requirement 1.8): a count, not forty rows.
    await store(engine, sensor, Pinout.parse(A_BIG_BOARD))

    async with catalog(engine) as work:
        with counting(engine) as statements:
            counted = await work.pinouts.count_of(sensor.id)

    assert counted == len(A_BIG_BOARD)
    assert len(statements) == 1, statements
    assert "count(*)" in statements[0]


async def test_replacing_a_pinout_is_a_delete_and_one_insert(
    engine: AsyncEngine, sensor: PartDefinition
) -> None:
    """Requirement 7.2: two statements for forty pins, and never one statement per pin."""
    async with catalog(engine) as work:
        with counting(engine) as statements:
            await work.pinouts.replace(sensor.id, Pinout.parse(A_BIG_BOARD))
        await work.commit()

    assert len(statements) == 2, statements
    assert statements[0].startswith("DELETE FROM pins")
    assert statements[1].startswith("INSERT INTO pins")
    assert len(await read(engine, sensor)) == len(A_BIG_BOARD)


async def test_clearing_a_pinout_is_the_delete_alone(
    engine: AsyncEngine, sensor: PartDefinition
) -> None:
    # No rows to insert, so no INSERT: an empty table is written with one statement.
    await store(engine, sensor, Pinout.parse(BME280_ROWS))

    async with catalog(engine) as work:
        with counting(engine) as statements:
            await work.pinouts.replace(sensor.id, Pinout.empty())
        await work.commit()

    assert len(statements) == 1, statements


async def test_a_refused_transaction_stores_no_pin_at_all(
    engine: AsyncEngine, sensor: PartDefinition
) -> None:
    """Requirement 1.3 as the database sees it: a replace left uncommitted never happened.

    The unit of work is what makes a pinout atomic — the `DELETE` and the `INSERT` are both
    undone — so a use case that refuses after writing can't leave a half-saved table.
    """
    await store(engine, sensor, Pinout.parse(BME280_ROWS))

    async with catalog(engine) as work:
        await work.pinouts.replace(sensor.id, Pinout.empty())
        # Left without commit(), as a refusal on the way out would leave it.

    assert await read(engine, sensor) == Pinout.parse(BME280_ROWS)
