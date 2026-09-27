"""The per-workspace short-code counter against a real PostgreSQL.

The one thing that can only be checked here: the `INSERT ... ON CONFLICT DO UPDATE ...
RETURNING` hands out gap-free numbers even when callers race, because the conflict path takes
the row lock and serializes them (requirement 2.2). Two workspaces keep separate counters.
"""

import asyncio
from collections.abc import AsyncIterator
from uuid import uuid7

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.settings import Environment, Settings
from wiredex.inventory.application.ports import ShortCodeKind
from wiredex.inventory.domain.values import WorkspaceId
from wiredex.inventory.infrastructure.unit_of_work import SqlInventoryUnitOfWork

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

ONE = WorkspaceId(uuid7())
ANOTHER = WorkspaceId(uuid7())


@pytest.fixture
async def engine(migrated_database_url: str) -> AsyncIterator[AsyncEngine]:
    settings = Settings(environment=Environment.TEST, database_url=SecretStr(migrated_database_url))
    engine = create_engine(settings)
    yield engine
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE short_code_counters CASCADE"))
    await engine.dispose()


def inventory(engine: AsyncEngine, workspace_id: WorkspaceId) -> SqlInventoryUnitOfWork:
    return SqlInventoryUnitOfWork(create_session_factory(engine), workspace_id)


async def mint_one(engine: AsyncEngine, workspace_id: WorkspaceId) -> int:
    """One number in its own transaction, committed, as a single receive would take it."""
    async with inventory(engine, workspace_id) as work:
        number = await work.short_codes.next(ShortCodeKind.LOCATION)
        await work.commit()
        return number


async def test_sequential_calls_count_up_from_one(engine: AsyncEngine) -> None:
    numbers = [await mint_one(engine, ONE) for _ in range(5)]

    assert numbers == [1, 2, 3, 4, 5]


async def test_concurrent_calls_in_one_workspace_are_distinct_and_gap_free(
    engine: AsyncEngine,
) -> None:
    # Ten transactions minting at once (the engine's pool tops out at ten). The row lock
    # serializes them, so the set is exactly 1..10: no number handed out twice, no gap
    # (requirement 2.2).
    numbers = await asyncio.gather(*(mint_one(engine, ONE) for _ in range(10)))

    assert sorted(numbers) == list(range(1, 11))


async def test_two_workspaces_number_independently(engine: AsyncEngine) -> None:
    # Each workspace has its own counter row, so both start at 1 and neither disturbs the
    # other's sequence.
    mine = [await mint_one(engine, ONE) for _ in range(3)]
    theirs = [await mint_one(engine, ANOTHER) for _ in range(2)]
    mine.append(await mint_one(engine, ONE))

    assert mine == [1, 2, 3, 4]
    assert theirs == [1, 2]


async def test_a_rolled_back_call_does_not_burn_a_number(engine: AsyncEngine) -> None:
    # The advance rides in the transaction: a call that never commits leaves the counter be,
    # so the next committed call still gets 1 (design's Short codes).
    async with inventory(engine, ONE) as work:
        await work.short_codes.next(ShortCodeKind.LOCATION)
        # No commit: leaving the block discards it.

    assert await mint_one(engine, ONE) == 1


async def test_locations_and_units_count_apart(engine: AsyncEngine) -> None:
    # Two kinds, two counter rows in one workspace: minting a location doesn't move the unit
    # counter, which the next spec's units rely on.
    async with inventory(engine, ONE) as work:
        first_location = await work.short_codes.next(ShortCodeKind.LOCATION)
        first_unit = await work.short_codes.next(ShortCodeKind.UNIT)
        second_location = await work.short_codes.next(ShortCodeKind.LOCATION)
        await work.commit()

    assert (first_location, second_location) == (1, 2)
    assert first_unit == 1


async def test_a_receipt_of_n_advances_the_unit_counter_n_times_gap_free(
    engine: AsyncEngine,
) -> None:
    # A unit receive mints one code per unit from the `unit` counter, in its one transaction:
    # a receipt of three, then of two, hands out 1..5 consecutively with no gap and no reuse
    # (requirements 2.1, 2.2), independent of the `location` counter, which stays untouched.
    async with inventory(engine, ONE) as work:
        first_receipt = [await work.short_codes.next(ShortCodeKind.UNIT) for _ in range(3)]
        await work.commit()
    async with inventory(engine, ONE) as work:
        second_receipt = [await work.short_codes.next(ShortCodeKind.UNIT) for _ in range(2)]
        await work.commit()

    # The location counter has never moved in this workspace: its first mint is still 1.
    async with inventory(engine, ONE) as work:
        first_location = await work.short_codes.next(ShortCodeKind.LOCATION)
        await work.commit()

    assert first_receipt == [1, 2, 3]
    assert second_receipt == [4, 5]
    assert first_location == 1
