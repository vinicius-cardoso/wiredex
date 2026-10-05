"""The history routes over the in-memory fakes: a bare FastAPI, no database.

The router's own contract (17-history, HTTP): the shapes on the wire the web builds on, the
page's and the page size's 422s, an unknown kind, and a timeline's 404. The workspace dependency is
a stub, because resolving it is identity's job and the composition root's wiring, which
`test_history_auth.py` covers.
"""

from typing import Any, get_args
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from httpx import Response

from support.history import (
    BENCH,
    FakeRecords,
    FakeRestorers,
    InMemoryHistoryUnitOfWork,
    a_part_edit,
)
from wiredex.history.api.router import HistoryUseCases, create_router
from wiredex.history.api.schemas import (
    ActionName,
    OperationName,
    RecordKindName,
    RowKindName,
    TimelineKindName,
)
from wiredex.history.application.history import ListActivity, ListTimeline, RestoreVersion
from wiredex.history.domain.history import (
    Action,
    Change,
    Operation,
    RecordKind,
    RecordRef,
    RowChange,
    RowKind,
)
from wiredex.history.domain.restore import EDITABLE_FIELDS
from wiredex.history.domain.values import ChangeId, WorkspaceId
from wiredex.shared_kernel.domain.paging import PageRequest

HISTORY = "/api/history"
PART = RecordRef(RecordKind.PART, uuid4(), "R 4k7")


async def the_bench(_request: Request) -> WorkspaceId:
    """What `bootstrap/app.py` builds from the session: the workspace this request acts in."""
    return BENCH


@pytest.fixture
def work() -> InMemoryHistoryUnitOfWork:
    return InMemoryHistoryUnitOfWork()


@pytest.fixture
def records() -> FakeRecords:
    found = FakeRecords()
    found.add(PART)
    return found


@pytest.fixture
def restorers() -> FakeRestorers:
    return FakeRestorers()


@pytest.fixture
def client(
    work: InMemoryHistoryUnitOfWork, records: FakeRecords, restorers: FakeRestorers
) -> TestClient:
    use_cases = HistoryUseCases(
        list_activity=ListActivity(work.for_workspace),
        list_timeline=ListTimeline(work.for_workspace, records),
        restore_version=RestoreVersion(work.for_workspace, restorers),
    )
    app = FastAPI()
    app.include_router(create_router(use_cases, the_bench), prefix="/api")
    return TestClient(app)


def answered(response: Response, status: int = 200) -> Any:
    assert response.status_code == status, response.text
    return response.json()


def test_the_feed_answers_each_change_as_the_web_reads_it(
    client: TestClient, work: InMemoryHistoryUnitOfWork
) -> None:
    pin = RowChange(
        RowKind.PIN, Operation.INSERT, False, None, None, {"number": "3", "label": "SDA"}
    )
    edit = a_part_edit(7, PART, {"name": "R", "mpn": None}, {"name": "R 4k7", "mpn": None})
    work.changes.hold(Change(edit.id, edit.occurred_at, "Owner", None, PART, (*edit.rows, pin), 25))

    body = answered(client.get(HISTORY))

    assert body == {
        "changes": [
            {
                "id": 7,
                "occurred_at": "2026-10-01T09:07:00Z",
                "actor": "Owner",
                "reason": None,
                "record": {"kind": "part", "id": str(PART.id), "label": "R 4k7"},
                "action": "edited",
                "rows": [
                    {
                        "kind": "part",
                        "operation": "update",
                        "label": "R 4k7",
                        "fields": [{"name": "name", "before": "R", "after": "R 4k7"}],
                    },
                    {
                        "kind": "pin",
                        "operation": "insert",
                        "label": "3 SDA",
                        "fields": [
                            {"name": "label", "before": None, "after": "SDA"},
                            {"name": "number", "before": None, "after": "3"},
                        ],
                    },
                ],
                "more_rows": 23,
                "restorable": True,
            }
        ],
        "total": 1,
        "page": 1,
        "page_size": 50,
    }


def test_a_change_by_wiredex_itself_names_no_one_and_isnt_always_restorable(
    client: TestClient, work: InMemoryHistoryUnitOfWork
) -> None:
    created = RowChange(RowKind.PART, Operation.INSERT, True, None, None, {"name": "R"})
    work.changes.hold(
        Change(ChangeId(3), a_part_edit(3).occurred_at, None, None, PART, (created,), 1)
    )

    [change] = answered(client.get(HISTORY))["changes"]

    assert (change["actor"], change["action"], change["restorable"]) == (None, "created", False)


def test_the_feed_pages_by_number_with_a_total(
    client: TestClient, work: InMemoryHistoryUnitOfWork
) -> None:
    work.changes.hold(*(a_part_edit(number) for number in range(1, 4)))

    first = answered(client.get(HISTORY, params={"page_size": 2}))
    second = answered(client.get(HISTORY, params={"page": 2, "page_size": 2}))

    assert [change["id"] for change in first["changes"]] == [3, 2]
    assert [change["id"] for change in second["changes"]] == [1]
    assert [(body["total"], body["page"], body["page_size"]) for body in (first, second)] == [
        (3, 1, 2),
        (3, 2, 2),
    ]


def test_a_page_is_the_first_of_50_unless_asked(
    client: TestClient, work: InMemoryHistoryUnitOfWork
) -> None:
    answered(client.get(HISTORY))
    answered(client.get(HISTORY, params={"page_size": 100}))
    asked = [page for step, page, _, _ in work.changes.asked if step == "page"]
    assert asked == [PageRequest(1, 50), PageRequest(1, 100)]


def test_a_page_past_the_end_answers_the_last_page(
    client: TestClient, work: InMemoryHistoryUnitOfWork
) -> None:
    work.changes.hold(*(a_part_edit(number) for number in range(1, 4)))

    body = answered(client.get(HISTORY, params={"page": 9}))

    assert (body["page"], body["total"]) == (1, 3)
    assert [change["id"] for change in body["changes"]] == [3, 2, 1]


@pytest.mark.parametrize(
    "params",
    [
        {"page_size": 0},
        {"page_size": 101},
        {"page_size": "all"},
        {"page": 0},
        {"page": 100_001},
        {"page": "two"},
    ],
)
def test_a_page_out_of_range_is_refused(
    client: TestClient, work: InMemoryHistoryUnitOfWork, params: dict[str, object]
) -> None:
    assert client.get(HISTORY, params=params).status_code == 422
    assert client.get(f"{HISTORY}/part/{PART.id}", params=params).status_code == 422
    assert work.changes.asked == []


def test_the_routes_take_a_page_and_its_size_and_no_cursor_or_limit(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    for path in (HISTORY, f"{HISTORY}/{{kind}}/{{record_id}}"):
        names = {parameter["name"] for parameter in paths[path]["get"]["parameters"]}
        assert {"page", "page_size"} <= names
        assert not names & {"cursor", "limit"}


def test_the_feed_is_narrowed_by_an_action_a_kind_and_a_name(
    client: TestClient, work: InMemoryHistoryUnitOfWork
) -> None:
    station = RecordRef(RecordKind.PROJECT, uuid4(), "Weather station")
    work.changes.hold(a_part_edit(1), a_part_edit(2, station), a_part_edit(3))

    by_kind = answered(client.get(HISTORY, params={"kind": "project"}))
    by_all = answered(
        client.get(HISTORY, params={"action": "edited", "kind": "project", "q": "STATION"})
    )
    by_other_action = answered(client.get(HISTORY, params={"action": "deleted"}))

    assert [change["id"] for change in by_kind["changes"]] == [2]
    assert [change["id"] for change in by_all["changes"]] == [2]
    assert by_other_action["changes"] == []


@pytest.mark.parametrize("params", [{"action": "renamed"}, {"kind": "board"}, {"q": "x" * 81}])
def test_a_filter_the_api_doesnt_know_is_refused(
    client: TestClient, work: InMemoryHistoryUnitOfWork, params: dict[str, str]
) -> None:
    assert client.get(HISTORY, params=params).status_code == 422
    assert work.changes.asked == []


def test_a_timeline_holds_its_records_changes_only(
    client: TestClient, work: InMemoryHistoryUnitOfWork
) -> None:
    work.changes.hold(a_part_edit(1, PART), a_part_edit(2))

    body = answered(client.get(f"{HISTORY}/part/{PART.id}"))

    assert [change["id"] for change in body["changes"]] == [1]
    assert (body["total"], body["page"], body["page_size"]) == (1, 1, 50)


def test_a_timeline_pages_by_number(client: TestClient, work: InMemoryHistoryUnitOfWork) -> None:
    work.changes.hold(*(a_part_edit(number, PART) for number in range(1, 6)), a_part_edit(6))

    body = answered(client.get(f"{HISTORY}/part/{PART.id}", params={"page": 3, "page_size": 2}))

    assert [change["id"] for change in body["changes"]] == [1]
    assert (body["total"], body["page"], body["page_size"]) == (5, 3, 2)


def test_a_timeline_of_a_record_that_isnt_live_is_a_404(client: TestClient) -> None:
    response = client.get(f"{HISTORY}/project/{uuid4()}")
    assert response.status_code == 404
    assert response.json()["detail"] == "that project doesn't exist"


@pytest.mark.parametrize("path", ["category", "location", "revision", "nonsense"])
def test_a_timeline_of_a_kind_without_one_is_refused(client: TestClient, path: str) -> None:
    assert client.get(f"{HISTORY}/{path}/{uuid4()}").status_code == 422


def test_a_timeline_needs_a_real_id(client: TestClient) -> None:
    assert client.get(f"{HISTORY}/part/not-an-id").status_code == 422


def test_the_names_on_the_wire_are_the_domains() -> None:
    assert set(get_args(RecordKindName.__value__)) == {kind.value for kind in RecordKind}
    assert set(get_args(TimelineKindName.__value__)) == {kind.value for kind in EDITABLE_FIELDS}
    assert set(get_args(RowKindName.__value__)) == {kind.value for kind in RowKind}
    assert set(get_args(OperationName.__value__)) == {operation.value for operation in Operation}
    assert set(get_args(ActionName.__value__)) == {action.value for action in Action}


# --- Restoring ---------------------------------------------------------------------------


def restore(client: TestClient, change_id: int | str) -> Response:
    response: Response = client.post(f"{HISTORY}/changes/{change_id}/restore")
    return response


def test_restoring_a_change_hands_its_plan_to_the_module_and_answers_204(
    client: TestClient, work: InMemoryHistoryUnitOfWork, restorers: FakeRestorers
) -> None:
    work.changes.hold(a_part_edit(4, PART))

    assert restore(client, 4).status_code == 204

    [(workspace_id, plan)] = restorers.put_back_plans
    assert workspace_id == BENCH
    assert plan.record == PART
    assert plan.fields["name"] == "R"


def test_restoring_a_change_the_workspace_doesnt_hold_is_a_404(
    client: TestClient, restorers: FakeRestorers
) -> None:
    response = restore(client, 99)
    assert response.status_code == 404
    assert response.json()["detail"] == "that change doesn't exist"
    assert restorers.put_back_plans == []


def test_a_change_that_cant_be_restored_is_a_409(
    client: TestClient, work: InMemoryHistoryUnitOfWork
) -> None:
    created = RowChange(RowKind.PART, Operation.INSERT, True, None, None, {"name": "R"})
    work.changes.hold(
        Change(ChangeId(5), a_part_edit(5).occurred_at, None, None, PART, (created,), 1)
    )

    response = restore(client, 5)

    assert response.status_code == 409
    assert "nothing to undo" in response.json()["detail"]


def test_a_restore_the_module_refuses_is_a_409_with_its_sentence(
    client: TestClient, work: InMemoryHistoryUnitOfWork, restorers: FakeRestorers
) -> None:
    work.changes.hold(a_part_edit(6, PART))
    restorers.refuse = "resistance is required"

    response = restore(client, 6)

    assert (response.status_code, response.json()["detail"]) == (409, "resistance is required")


def test_a_restore_of_a_record_gone_since_is_a_404(
    client: TestClient, work: InMemoryHistoryUnitOfWork, restorers: FakeRestorers
) -> None:
    work.changes.hold(a_part_edit(8, PART))
    restorers.gone.add(PART.id)
    assert restore(client, 8).status_code == 404


@pytest.mark.parametrize("change_id", ["0", "-1", "abc", str(2**63)])
def test_a_change_id_out_of_range_is_refused(client: TestClient, change_id: str) -> None:
    assert restore(client, change_id).status_code == 422
