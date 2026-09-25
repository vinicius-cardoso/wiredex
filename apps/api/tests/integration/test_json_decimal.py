"""JSONB numbers have to be exact: every number the catalog stores is a Decimal."""

from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import Column, MetaData, Table, insert, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncEngine

from wiredex.bootstrap.database import create_engine
from wiredex.bootstrap.settings import Environment, Settings

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

# A probe table: the catalog's own tables arrive in a later migration.
metadata = MetaData()
probe = Table("json_probe", metadata, Column("attributes", JSONB, nullable=False))

# 100nF as parse_si stores it, and a number with more digits than a double holds, so
# this fails if a Decimal ever travels as a float.
EXACT: dict[str, Any] = {
    "capacitance": Decimal("1E-7"),
    "tolerance": Decimal("1.000000000000000000001"),
}


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    settings = Settings(environment=Environment.TEST, database_url=SecretStr(database_url))
    engine = create_engine(settings)
    async with engine.begin() as connection:
        await connection.run_sync(metadata.drop_all)
        await connection.run_sync(metadata.create_all)
    yield engine
    async with engine.begin() as connection:
        await connection.run_sync(metadata.drop_all)
    await engine.dispose()


async def store(engine: AsyncEngine, attributes: dict[str, Any]) -> None:
    async with engine.begin() as connection:
        await connection.execute(insert(probe).values(attributes=attributes))


async def stored(engine: AsyncEngine) -> list[dict[str, Any]]:
    async with engine.connect() as connection:
        rows = await connection.execute(select(probe.c.attributes))
        return list(rows.scalars())


async def test_decimals_come_back_as_the_decimals_they_were(engine: AsyncEngine) -> None:
    await store(engine, EXACT)

    [attributes] = await stored(engine)

    assert attributes == EXACT
    assert all(isinstance(number, Decimal) for number in attributes.values())


async def test_a_decimal_is_written_as_a_json_number(engine: AsyncEngine) -> None:
    await store(engine, EXACT)

    async with engine.connect() as connection:
        kind = await connection.execute(
            text("SELECT jsonb_typeof(attributes -> 'capacitance') FROM json_probe")
        )

    # A quoted number would keep its digits and lose `@>` against the GIN index.
    assert kind.scalar_one() == "number"


async def test_one_magnitude_spelled_two_ways_is_stored_as_one_value(engine: AsyncEngine) -> None:
    await store(engine, {"resistance": Decimal("1E4")})  # 10k
    await store(engine, {"resistance": Decimal("10000")})

    # A whole number reads back as an int, exact as well, and equal either way.
    assert [row["resistance"] for row in await stored(engine)] == [Decimal(10000)] * 2
