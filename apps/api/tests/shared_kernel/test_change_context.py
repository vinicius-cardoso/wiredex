"""Who and why, as a task carries them to the transactions it opens (17-history, decision 4)."""

import asyncio
from uuid import uuid7

from wiredex.shared_kernel.infrastructure.change_context import (
    Actor,
    act_as,
    acting,
    changing_for,
    reason,
)


def test_a_reason_holds_for_its_block_only() -> None:
    assert reason() is None
    with changing_for("restore"):
        assert reason() == "restore"
        with changing_for("import"):
            assert reason() == "import"
        assert reason() == "restore"
    assert reason() is None


def test_an_actor_stays_inside_the_task_that_set_it() -> None:
    owner = Actor(uuid7(), "Owner")

    async def request() -> Actor | None:
        act_as(owner)
        return acting()

    async def next_request() -> Actor | None:
        return acting()

    # Each `asyncio.run` is a task of its own, as each request is: nothing leaks between them.
    assert asyncio.run(request()) == owner
    assert asyncio.run(next_request()) is None
    assert acting() is None
