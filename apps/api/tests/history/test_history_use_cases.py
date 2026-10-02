"""History's use cases over the in-memory fakes (17-history)."""

from uuid import uuid4, uuid7

import pytest

from support.history import (
    BENCH,
    FakeRecords,
    FakeRestorers,
    InMemoryHistoryUnitOfWork,
    a_part_edit,
)
from wiredex.history.application.history import (
    ClearHistory,
    ListActivity,
    ListTimeline,
    RestoreVersion,
)
from wiredex.history.domain.errors import (
    ChangeNotFoundError,
    NotRestorableError,
    RecordNotFoundError,
)
from wiredex.history.domain.history import ChangeCursor, RecordKind, RecordRef
from wiredex.history.domain.values import ChangeId, WorkspaceId

pytestmark = pytest.mark.anyio

PART = RecordRef(RecordKind.PART, uuid4(), "R 4k7")


async def test_the_feed_reads_newest_first_a_page_at_a_time() -> None:
    work = InMemoryHistoryUnitOfWork()
    work.changes.hold(*(a_part_edit(number) for number in range(1, 6)))
    list_activity = ListActivity(work.for_workspace)

    first = await list_activity(BENCH, None, 2)
    assert first.next is not None
    second = await list_activity(BENCH, first.next, 10)

    assert [change.id for change in first.changes] == [5, 4]
    assert [change.id for change in second.changes] == [3, 2, 1]
    assert second.next is None
    # One more than the page holds, to know whether a next one exists.
    assert work.changes.asked == [(None, 3, None), (ChangeId(4), 11, None)]


async def test_a_timeline_reads_its_records_changes_once_the_module_has_it() -> None:
    work = InMemoryHistoryUnitOfWork()
    records = FakeRecords()
    records.add(PART)
    work.changes.hold(a_part_edit(1, PART), a_part_edit(2), a_part_edit(3, PART))

    page = await ListTimeline(work.for_workspace, records)(BENCH, (PART.kind, PART.id), None, 50)

    assert [change.id for change in page.changes] == [3, 1]
    assert records.asked == [(PART.kind, PART.id)]


async def test_a_timeline_of_a_record_that_isnt_live_is_a_404_and_reads_no_history() -> None:
    # Requirement 3.2: in the trash, deleted, or another bench's, as on its page.
    work = InMemoryHistoryUnitOfWork()
    records = FakeRecords()
    records.add(PART, workspace_id=WorkspaceId(uuid7()))

    with pytest.raises(RecordNotFoundError, match="that part doesn't exist"):
        await ListTimeline(work.for_workspace, records)(BENCH, (PART.kind, PART.id), None, 50)
    assert work.opened_for == []


async def test_a_timeline_with_nothing_recorded_is_empty() -> None:
    # Requirement 3.3: history starts with the first change after the upgrade.
    work = InMemoryHistoryUnitOfWork()
    records = FakeRecords()
    records.add(PART)

    page = await ListTimeline(work.for_workspace, records)(
        BENCH, (PART.kind, PART.id), ChangeCursor(ChangeId(9)), 50
    )

    assert page.changes == ()
    assert page.next is None


async def test_clearing_deletes_a_benchs_changes_and_commits() -> None:
    # Requirement 5.4: a demo bench just seeded starts with no history.
    work = InMemoryHistoryUnitOfWork()
    other = WorkspaceId(uuid7())
    work.changes.hold(a_part_edit(2), a_part_edit(1))
    work.changes.hold(a_part_edit(3), workspace_id=other)

    cleared = await ClearHistory(work.for_workspace)(BENCH)

    assert cleared == 2
    assert work.changes.saved[BENCH] == []
    assert len(work.changes.saved[other]) == 1
    assert work.opened_for == [BENCH]
    assert work.commits == 1


async def test_a_restore_hands_the_version_before_the_change_to_the_records_module() -> None:
    work = InMemoryHistoryUnitOfWork()
    restorers = FakeRestorers()
    work.changes.hold(
        a_part_edit(4, PART, {"name": "R", "mpn": "A"}, {"name": "R 4k7", "mpn": "A"})
    )

    await RestoreVersion(work.for_workspace, restorers)(BENCH, ChangeId(4))

    [(workspace_id, plan)] = restorers.put_back_plans
    assert (workspace_id, plan.record) == (BENCH, PART)
    assert (plan.fields["name"], plan.fields["mpn"]) == ("R", "A")
    assert restorers.out_of_trash == []
    # Read in history's transaction, nothing committed there: the module's edit writes.
    assert work.commits == 0


async def test_a_move_to_the_trash_is_restored_from_the_trash() -> None:
    work = InMemoryHistoryUnitOfWork()
    restorers = FakeRestorers()
    moved = "2026-10-01T09:00:00+00:00"
    edit = a_part_edit(5, PART, {"trashed_at": None}, {"trashed_at": moved})
    work.changes.hold(edit)

    await RestoreVersion(work.for_workspace, restorers)(BENCH, ChangeId(5))

    assert restorers.out_of_trash == [(BENCH, PART)]
    assert restorers.put_back_plans == []


async def test_a_restore_of_a_change_the_workspace_doesnt_hold_is_a_404() -> None:
    work = InMemoryHistoryUnitOfWork()
    work.changes.hold(a_part_edit(6), workspace_id=WorkspaceId(uuid7()))
    with pytest.raises(ChangeNotFoundError):
        await RestoreVersion(work.for_workspace, FakeRestorers())(BENCH, ChangeId(6))


async def test_what_the_module_refuses_reaches_the_caller() -> None:
    work = InMemoryHistoryUnitOfWork()
    restorers = FakeRestorers()
    restorers.refuse = "another part already uses that MPN"
    work.changes.hold(a_part_edit(7, PART))

    with pytest.raises(NotRestorableError, match="already uses that MPN"):
        await RestoreVersion(work.for_workspace, restorers)(BENCH, ChangeId(7))
