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
from wiredex.history.domain.history import ActivityFilter, RecordKind, RecordRef
from wiredex.history.domain.values import ChangeId, WorkspaceId
from wiredex.shared_kernel.domain.paging import PageRequest

pytestmark = pytest.mark.anyio

PART = RecordRef(RecordKind.PART, uuid4(), "R 4k7")


async def test_the_feed_reads_newest_first_a_numbered_page_at_a_time() -> None:
    work = InMemoryHistoryUnitOfWork()
    work.changes.hold(*(a_part_edit(number) for number in range(1, 6)))
    list_activity = ListActivity(work.for_workspace)

    first = await list_activity(BENCH, PageRequest(1, 2))
    second = await list_activity(BENCH, PageRequest(2, 2))
    third = await list_activity(BENCH, PageRequest(3, 2))

    assert [[change.id for change in page.items] for page in (first, second, third)] == [
        [5, 4],
        [3, 2],
        [1],
    ]
    assert {page.total for page in (first, second, third)} == {5}
    assert third.request == PageRequest(3, 2)
    # Counted first, in the same unit of work, then the page read.
    assert work.changes.asked[:2] == [
        ("count", None, None, None),
        ("page", PageRequest(1, 2), None, None),
    ]
    assert work.opened_for == [BENCH, BENCH, BENCH]


async def test_a_page_past_the_end_of_the_feed_is_its_last_page() -> None:
    work = InMemoryHistoryUnitOfWork()
    work.changes.hold(*(a_part_edit(number) for number in range(1, 4)))

    page = await ListActivity(work.for_workspace)(BENCH, PageRequest(9, 2))

    assert page.request == PageRequest(2, 2)
    assert [change.id for change in page.items] == [1]
    assert page.total == 3
    assert work.changes.asked[-1] == ("page", PageRequest(2, 2), None, None)


async def test_an_empty_feed_is_one_empty_page() -> None:
    work = InMemoryHistoryUnitOfWork()

    page = await ListActivity(work.for_workspace)(BENCH, PageRequest(4))

    assert (page.items, page.total, page.request) == ((), 0, PageRequest(1))


async def test_the_feed_is_counted_and_paged_by_the_same_narrowing() -> None:
    work = InMemoryHistoryUnitOfWork()
    station = RecordRef(RecordKind.PROJECT, uuid4(), "Weather station")
    work.changes.hold(a_part_edit(1), a_part_edit(2, station), a_part_edit(3))
    list_activity = ListActivity(work.for_workspace)
    wanted = ActivityFilter(kind=RecordKind.PROJECT, text="station")

    page = await list_activity(BENCH, PageRequest(), wanted)

    assert [change.id for change in page.items] == [2]
    assert page.total == 1
    assert work.changes.asked == [
        ("count", None, None, wanted),
        ("page", PageRequest(), None, wanted),
    ]


async def test_a_timeline_reads_its_records_changes_once_the_module_has_it() -> None:
    work = InMemoryHistoryUnitOfWork()
    records = FakeRecords()
    records.add(PART)
    work.changes.hold(a_part_edit(1, PART), a_part_edit(2), a_part_edit(3, PART))
    record = (PART.kind, PART.id)

    page = await ListTimeline(work.for_workspace, records)(BENCH, record, PageRequest())

    assert [change.id for change in page.items] == [3, 1]
    assert page.total == 2
    assert records.asked == [record]
    assert work.changes.asked == [
        ("count", None, record, None),
        ("page", PageRequest(), record, None),
    ]


async def test_a_page_past_the_end_of_a_timeline_is_its_last_page() -> None:
    work = InMemoryHistoryUnitOfWork()
    records = FakeRecords()
    records.add(PART)
    work.changes.hold(*(a_part_edit(number, PART) for number in range(1, 6)))

    page = await ListTimeline(work.for_workspace, records)(
        BENCH, (PART.kind, PART.id), PageRequest(7, 2)
    )

    assert page.request == PageRequest(3, 2)
    assert [change.id for change in page.items] == [1]


async def test_a_timeline_of_a_record_that_isnt_live_is_a_404_and_reads_no_history() -> None:
    # Requirement 3.2: in the trash, deleted, or another bench's, as on its page.
    work = InMemoryHistoryUnitOfWork()
    records = FakeRecords()
    records.add(PART, workspace_id=WorkspaceId(uuid7()))

    with pytest.raises(RecordNotFoundError, match="that part doesn't exist"):
        await ListTimeline(work.for_workspace, records)(BENCH, (PART.kind, PART.id), PageRequest())
    assert work.opened_for == []
    assert work.changes.asked == []


async def test_a_timeline_with_nothing_recorded_is_empty() -> None:
    # Requirement 3.3: history starts with the first change after the upgrade.
    work = InMemoryHistoryUnitOfWork()
    records = FakeRecords()
    records.add(PART)

    page = await ListTimeline(work.for_workspace, records)(
        BENCH, (PART.kind, PART.id), PageRequest(3)
    )

    assert (page.items, page.total, page.request) == ((), 0, PageRequest(1))


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
