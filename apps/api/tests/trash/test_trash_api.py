"""The trash routes over in-memory bins: a bare FastAPI, no database.

The router's own contract (16-soft-delete-and-trash, HTTP): every route's status, the shapes on
the wire the web builds on, the limit's and the cursor's 422s, and a record not in the trash a
404. The workspace dependency is a stub, because resolving it is identity's job and the
composition root's wiring, which `test_trash_auth.py` covers.
"""

from typing import Any, get_args
from uuid import uuid7

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from httpx import Response

from support.trash import BENCH, Trash, an_item
from wiredex.trash.api.router import TrashUseCases, create_router
from wiredex.trash.api.schemas import TrashKindName
from wiredex.trash.domain.trash import MAX_CURSOR_LENGTH, TrashKind
from wiredex.trash.domain.values import WorkspaceId

TRASH = "/api/trash"


async def the_bench(_request: Request) -> WorkspaceId:
    """What `bootstrap/app.py` builds from the session: the workspace this request acts in."""
    return BENCH


@pytest.fixture
def trash() -> Trash:
    return Trash()


@pytest.fixture
def client(trash: Trash) -> TestClient:
    use_cases = TrashUseCases(
        list_trash=trash.list_trash,
        restore_from_trash=trash.restore,
        delete_from_trash=trash.delete,
        empty_trash=trash.empty,
    )
    app = FastAPI()
    app.include_router(create_router(use_cases, the_bench), prefix="/api")
    return TestClient(app)


def answered(response: Response, status: int = 200) -> Any:
    assert response.status_code == status, response.text
    return response.json()


def test_the_trash_reads_newest_first_in_the_wire_shape(client: TestClient, trash: Trash) -> None:
    part = an_item(TrashKind.PART, 1, "4.7 kΩ 1% 0805", "RC0805FR-074K7L")
    project = an_item(TrashKind.PROJECT, 2, "Weather station")
    trash.hold(part, project)

    body = answered(client.get(TRASH))

    assert body == {
        "items": [
            {
                "kind": "project",
                "id": str(project.id),
                "name": "Weather station",
                "detail": None,
                "trashed_at": "2026-10-01T09:02:00Z",
            },
            {
                "kind": "part",
                "id": str(part.id),
                "name": "4.7 kΩ 1% 0805",
                "detail": "RC0805FR-074K7L",
                "trashed_at": "2026-10-01T09:01:00Z",
            },
        ],
        "next_cursor": None,
    }


def test_an_empty_trash_is_an_empty_list(client: TestClient) -> None:
    # Requirement 4.5.
    assert answered(client.get(TRASH)) == {"items": [], "next_cursor": None}


def test_a_page_is_50_unless_asked(client: TestClient, trash: Trash) -> None:
    # Requirement 4.2: each bin is asked for one more, to know whether a next page exists.
    answered(client.get(TRASH))
    answered(client.get(TRASH, params={"limit": 100}))
    for trash_bin in trash.bins.values():
        assert [limit for _, limit in trash_bin.asked] == [51, 101]


@pytest.mark.parametrize("limit", [0, -1, 101, "many"])
def test_a_limit_out_of_range_is_refused(client: TestClient, trash: Trash, limit: object) -> None:
    assert client.get(TRASH, params={"limit": limit}).status_code == 422
    assert trash.log == []


def test_the_cursor_reads_the_next_page(client: TestClient, trash: Trash) -> None:
    # Requirement 4.3.
    items = [an_item(TrashKind.UNIT, minutes) for minutes in range(3)]
    trash.hold(*items)

    first = answered(client.get(TRASH, params={"limit": 2}))
    assert [item["id"] for item in first["items"]] == [str(items[2].id), str(items[1].id)]
    assert first["next_cursor"] is not None
    second = answered(client.get(TRASH, params={"limit": 2, "cursor": first["next_cursor"]}))

    assert [item["id"] for item in second["items"]] == [str(items[0].id)]
    assert second["next_cursor"] is None


@pytest.mark.parametrize("cursor", ["", "not a cursor", "A" * MAX_CURSOR_LENGTH])
def test_a_cursor_the_api_didnt_give_is_refused(
    client: TestClient, trash: Trash, cursor: str
) -> None:
    # Requirement 4.4.
    response = client.get(TRASH, params={"cursor": cursor})
    assert response.status_code == 422
    assert response.json()["detail"] == "this cursor can't be read"
    assert trash.log == []


def test_a_cursor_past_its_length_is_refused_before_reading(
    client: TestClient, trash: Trash
) -> None:
    assert client.get(TRASH, params={"cursor": "A" * (MAX_CURSOR_LENGTH + 1)}).status_code == 422
    assert trash.log == []


@pytest.mark.parametrize("kind", list(TrashKind))
def test_a_record_is_restored_once(client: TestClient, trash: Trash, kind: TrashKind) -> None:
    # Requirements 5.1 and 5.3: a second restore finds nothing in the trash.
    item = an_item(kind, 1)
    trash.hold(item)
    path = f"{TRASH}/{kind.value}/{item.id}/restore"

    assert client.post(path).status_code == 204
    assert trash.held() == []
    second = client.post(path)
    assert second.status_code == 404
    assert second.json()["detail"] == f"that {kind.value} isn't in the trash"


@pytest.mark.parametrize("kind", list(TrashKind))
def test_a_record_is_deleted_for_good_once(
    client: TestClient, trash: Trash, kind: TrashKind
) -> None:
    # Requirements 6.1 and 6.2.
    item = an_item(kind, 1)
    trash.hold(item)
    path = f"{TRASH}/{kind.value}/{item.id}"

    assert client.delete(path).status_code == 204
    assert trash.held() == []
    assert client.delete(path).status_code == 404


def test_a_record_named_as_another_kind_is_a_404(client: TestClient, trash: Trash) -> None:
    part = an_item(TrashKind.PART, 1)
    trash.hold(part)
    assert client.post(f"{TRASH}/project/{part.id}/restore").status_code == 404
    assert client.delete(f"{TRASH}/firmware/{part.id}").status_code == 404
    assert trash.held() == [part]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", f"{TRASH}/revision/{uuid7()}/restore"),
        ("DELETE", f"{TRASH}/category/{uuid7()}"),
        ("POST", f"{TRASH}/part/not-an-id/restore"),
        ("DELETE", f"{TRASH}/unit/not-an-id"),
    ],
)
def test_an_unknown_kind_or_a_malformed_id_is_refused(
    client: TestClient, trash: Trash, method: str, path: str
) -> None:
    assert client.request(method, path).status_code == 422
    assert trash.log == []


def test_emptying_deletes_everything_for_good(client: TestClient, trash: Trash) -> None:
    # Requirement 6.4.
    trash.hold(*(an_item(kind, minutes) for minutes, kind in enumerate(TrashKind)))

    assert client.delete(TRASH).status_code == 204

    assert trash.held() == []
    assert answered(client.get(TRASH))["items"] == []


def test_the_kind_names_on_the_wire_are_the_domains() -> None:
    assert set(get_args(TrashKindName.__value__)) == {kind.value for kind in TrashKind}
