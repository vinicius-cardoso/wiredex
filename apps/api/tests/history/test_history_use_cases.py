"""History's use cases over the in-memory fakes (17-history)."""

from datetime import UTC, datetime
from uuid import uuid4, uuid7

import pytest

from support.history import BENCH, InMemoryHistoryUnitOfWork
from wiredex.history.application.history import ClearHistory
from wiredex.history.domain.history import Change, RecordKind, RecordRef
from wiredex.history.domain.values import ChangeId, WorkspaceId

pytestmark = pytest.mark.anyio

AT = datetime(2026, 10, 1, 9, tzinfo=UTC)


def a_change(number: int) -> Change:
    record = RecordRef(RecordKind.PART, uuid4(), "R 4k7")
    return Change(ChangeId(number), AT, "Owner", None, record, (), 1)


async def test_clearing_deletes_a_benchs_changes_and_commits() -> None:
    # Requirement 5.4: a demo bench just seeded starts with no history.
    work = InMemoryHistoryUnitOfWork()
    other = WorkspaceId(uuid7())
    work.changes.saved = {BENCH: [a_change(2), a_change(1)], other: [a_change(3)]}

    cleared = await ClearHistory(work.for_workspace)(BENCH)

    assert cleared == 2
    assert work.changes.saved[BENCH] == []
    assert len(work.changes.saved[other]) == 1
    assert work.opened_for == [BENCH]
    assert work.commits == 1
