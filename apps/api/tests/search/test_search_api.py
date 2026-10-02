"""The search route over in-memory sources: a bare FastAPI, no database.

The router's own contract (19-command-palette, HTTP): the shape on the wire the web builds on,
the text's and the limit's 422s, and the limit the sources are asked for. The workspace
dependency is a stub, because resolving it is identity's job and the composition root's wiring,
which `test_search_auth.py` covers.
"""

from typing import Any, get_args

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from httpx import Response

from support.search import BENCH, FakeSource, sources
from wiredex.search.api.router import SearchUseCases, create_router
from wiredex.search.api.schemas import SearchKindName
from wiredex.search.application.search import SearchWorkspace
from wiredex.search.domain.search import SearchKind
from wiredex.search.domain.values import WorkspaceId

SEARCH = "/api/search"


async def the_bench(_request: Request) -> WorkspaceId:
    """What `bootstrap/app.py` builds from the session: the workspace this request acts in."""
    return BENCH


@pytest.fixture
def held() -> dict[SearchKind, FakeSource]:
    return sources()


@pytest.fixture
def client(held: dict[SearchKind, FakeSource]) -> TestClient:
    use_cases = SearchUseCases(search_workspace=SearchWorkspace(list(held.values())))
    app = FastAPI()
    app.include_router(create_router(use_cases, the_bench), prefix="/api")
    return TestClient(app)


def answered(response: Response, status: int = 200) -> Any:
    assert response.status_code == status, response.text
    return response.json()


def test_the_search_answers_each_kinds_group_in_the_wire_shape(
    client: TestClient, held: dict[SearchKind, FakeSource]
) -> None:
    (part,) = held[SearchKind.PART].hold("Sensor BME280", detail="Bosch · BME280")
    (unit,) = held[SearchKind.UNIT].hold("Sensor board WX-U-0001")

    body = answered(client.get(SEARCH, params={"q": " sensor "}))

    assert body == {
        "query": "sensor",
        "groups": [
            {
                "kind": "part",
                "hits": [
                    {"id": str(part.id), "title": "Sensor BME280", "detail": "Bosch · BME280"}
                ],
                "more": False,
            },
            {
                "kind": "unit",
                "hits": [{"id": str(unit.id), "title": "Sensor board WX-U-0001", "detail": None}],
                "more": False,
            },
        ],
    }


def test_five_hits_a_kind_unless_asked_and_whether_more_match(
    client: TestClient, held: dict[SearchKind, FakeSource]
) -> None:
    # Requirement 1.4.
    held[SearchKind.PART].hold(*(f"Sensor {index}" for index in range(7)))

    default = answered(client.get(SEARCH, params={"q": "sensor"}))
    asked = answered(client.get(SEARCH, params={"q": "sensor", "limit": 20}))

    assert [len(default["groups"][0]["hits"]), default["groups"][0]["more"]] == [5, True]
    assert [len(asked["groups"][0]["hits"]), asked["groups"][0]["more"]] == [7, False]
    assert {entry.limit for entry in held[SearchKind.PART].log} == {6, 21}


def test_nothing_found_answers_no_group(client: TestClient) -> None:
    assert answered(client.get(SEARCH, params={"q": "sensor"})) == {"query": "sensor", "groups": []}


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"q": "   "},
        {"q": "x" * 101},
        {"q": "sensor", "limit": 0},
        {"q": "sensor", "limit": 21},
    ],
)
def test_a_text_or_limit_outside_the_rules_is_refused_and_asks_nothing(
    client: TestClient, held: dict[SearchKind, FakeSource], params: dict[str, Any]
) -> None:
    # Requirements 1.4 and 1.5.
    answered(client.get(SEARCH, params=params), 422)
    assert held[SearchKind.PART].log == []


def test_the_wire_kinds_are_the_search_kinds() -> None:
    assert list(get_args(SearchKindName.__value__)) == [kind.value for kind in SearchKind]
