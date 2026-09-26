"""The search and facets routes over the in-memory fakes, as the other catalog routes are.

What is asserted here is the wire, not the search rules (those are test_search_use_cases):
the body's discriminated union reaches the use case as the right typed filter, a refused
filter answers 422 with a message that names it, a page carries an opaque cursor a client
sends straight back, the result rows carry the category's number and enum columns, and the
facets come back in the shape design's HTTP API draws.

The bench is the fakes' *Passives → Resistors* with a required `resistance` in ohms; each
test defines the attributes and parts it needs through the same routes a client would.
"""

from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from support.catalog import BENCH, World
from wiredex.catalog.api.router import create_router
from wiredex.catalog.domain.values import WorkspaceId

CATALOG = "/api/catalog"


async def the_bench(_request: Request) -> WorkspaceId:
    """What bootstrap/app.py builds from the session: the workspace this request acts in."""
    return BENCH


@pytest.fixture
def world() -> World:
    return World()


@pytest.fixture
def client(world: World) -> TestClient:
    app = FastAPI()
    app.include_router(create_router(world.catalog_use_cases(), the_bench), prefix="/api")
    return TestClient(app)


def define_part(client: TestClient, world: World, name: str, attributes: dict[str, Any]) -> str:
    """Defines a resistor through the API and returns its id, so a test gets on with its point."""
    response = client.post(
        f"{CATALOG}/parts",
        json={"category_id": str(world.resistors.id), "name": name, "attributes": attributes},
    )
    assert response.status_code == 201, response.text
    part_id: str = response.json()["id"]
    return part_id


def define_choice(client: TestClient, world: World, key: str, options: list[str]) -> None:
    response = client.post(
        f"{CATALOG}/categories/{world.resistors.id}/attributes",
        json={"key": key, "label": key, "kind": "enum", "options": options},
    )
    assert response.status_code == 201, response.text


def search(client: TestClient, body: dict[str, Any]) -> dict[str, Any]:
    response = client.post(f"{CATALOG}/parts/search", json=body)
    assert response.status_code == 200, response.text
    page: dict[str, Any] = response.json()
    return page


def result_names(page: dict[str, Any]) -> list[str]:
    return [item["name"] for item in page["items"]]


# --- The body's discriminated union reaches the use case ------------------------------


def test_a_range_filter_narrows_by_the_attribute_value(client: TestClient, world: World) -> None:
    # Requirement 2.1: the `range` shape of the union, read as a number filter.
    define_part(client, world, "R 4k7", {"resistance": "4k7"})
    define_part(client, world, "R 10k", {"resistance": "10k"})
    define_part(client, world, "R 220R", {"resistance": "220R"})

    page = search(
        client,
        {
            "category_id": str(world.resistors.id),
            "filters": [{"type": "range", "key": "resistance", "minimum": "1k", "maximum": "10k"}],
            "sort": "attribute:resistance",
            "direction": "asc",
        },
    )

    assert result_names(page) == ["R 4k7", "R 10k"]


def test_an_options_filter_matches_any_of_the_chosen(client: TestClient, world: World) -> None:
    # Requirement 2.3: the `options` shape of the union.
    define_choice(client, world, "mounting", ["smd", "through-hole"])
    define_part(client, world, "SMD one", {"resistance": "1k", "mounting": "smd"})
    define_part(client, world, "Through one", {"resistance": "1k", "mounting": "through-hole"})

    page = search(
        client,
        {
            "category_id": str(world.resistors.id),
            "filters": [{"type": "options", "key": "mounting", "options": ["smd"]}],
        },
    )

    assert result_names(page) == ["SMD one"]


def test_a_bool_filter_matches_the_value_asked_for(client: TestClient, world: World) -> None:
    # Requirement 2.4: the `bool` shape of the union.
    client.post(
        f"{CATALOG}/categories/{world.resistors.id}/attributes",
        json={"key": "rohs", "label": "RoHS", "kind": "bool"},
    )
    define_part(client, world, "Compliant", {"resistance": "1k", "rohs": True})
    define_part(client, world, "Not compliant", {"resistance": "1k", "rohs": False})

    page = search(
        client,
        {
            "category_id": str(world.resistors.id),
            "filters": [{"type": "bool", "key": "rohs", "value": True}],
        },
    )

    assert result_names(page) == ["Compliant"]


def test_a_text_filter_matches_a_fragment(client: TestClient, world: World) -> None:
    # Requirement 2.5: the `text` shape of the union.
    client.post(
        f"{CATALOG}/categories/{world.resistors.id}/attributes",
        json={"key": "note", "label": "Note", "kind": "text"},
    )
    define_part(client, world, "Noted", {"resistance": "1k", "note": "high precision"})
    define_part(client, world, "Plain", {"resistance": "1k", "note": "generic"})

    page = search(
        client,
        {
            "category_id": str(world.resistors.id),
            "filters": [{"type": "text", "key": "note", "text": "precision"}],
        },
    )

    assert result_names(page) == ["Noted"]


# --- 422 naming the filter -------------------------------------------------------------


def test_a_filter_without_a_category_is_refused_naming_the_reason(client: TestClient) -> None:
    # Requirement 2.8: an attribute filter needs a category to read its key.
    response = client.post(
        f"{CATALOG}/parts/search",
        json={"filters": [{"type": "range", "key": "resistance", "minimum": "1k"}]},
    )

    assert response.status_code == 422
    assert "resistance" in response.json()["detail"]
    assert "category" in response.json()["detail"]


def test_a_filter_on_an_unknown_key_is_refused_naming_it(client: TestClient, world: World) -> None:
    # Requirement 2.9: the message names the filter the resolved schema doesn't define.
    response = client.post(
        f"{CATALOG}/parts/search",
        json={
            "category_id": str(world.resistors.id),
            "filters": [{"type": "range", "key": "resistence", "minimum": "1k"}],
        },
    )

    assert response.status_code == 422
    assert "resistence" in response.json()["detail"]


def test_a_range_on_an_enum_is_refused_naming_the_filter(client: TestClient, world: World) -> None:
    # Requirement 2.9: a range doesn't fit an enum's kind, and the message says which key.
    define_choice(client, world, "mounting", ["smd", "through-hole"])

    response = client.post(
        f"{CATALOG}/parts/search",
        json={
            "category_id": str(world.resistors.id),
            "filters": [{"type": "range", "key": "mounting", "minimum": "1"}],
        },
    )

    assert response.status_code == 422
    assert "mounting" in response.json()["detail"]


# --- The results' columns and the cursor -----------------------------------------------


def test_a_result_row_carries_the_categorys_number_and_enum_values(
    client: TestClient, world: World
) -> None:
    # Requirement 6.3: the columns the web adds for a chosen category travel with each row,
    # the number in the three forms a value takes on the wire (value, display, unit).
    define_choice(client, world, "mounting", ["smd", "through-hole"])
    define_part(client, world, "R 4k7", {"resistance": "4k7", "mounting": "smd"})

    page = search(client, {"category_id": str(world.resistors.id)})

    row = page["items"][0]
    assert row["attributes"]["resistance"] == {"value": "4700", "display": "4.7k", "unit": "Ω"}
    assert row["attributes"]["mounting"]["value"] == "smd"


def test_a_search_without_a_category_carries_no_columns(client: TestClient, world: World) -> None:
    # Requirement 6.3: no category, no schema, so no attribute columns on the rows.
    define_part(client, world, "R 4k7", {"resistance": "4k7"})

    page = search(client, {})

    assert page["items"][0]["attributes"] == {}


def test_a_full_page_returns_a_cursor_that_continues_the_search(
    client: TestClient, world: World
) -> None:
    # Requirement 4.3: the opaque cursor a client sends straight back, and the next page
    # carries the parts the first one didn't, none repeated.
    for index in range(3):
        define_part(client, world, f"R {index}", {"resistance": f"{index + 1}k"})

    first = search(client, {"category_id": str(world.resistors.id), "limit": 2})

    assert len(first["items"]) == 2
    assert first["next_cursor"] is not None

    second = search(
        client, {"category_id": str(world.resistors.id), "limit": 2, "cursor": first["next_cursor"]}
    )

    assert len(second["items"]) == 1
    assert second["next_cursor"] is None
    seen = set(result_names(first)) | set(result_names(second))
    assert seen == {"R 0", "R 1", "R 2"}


def test_a_cursor_from_another_search_is_refused(client: TestClient, world: World) -> None:
    # Requirement 4.4: a cursor replayed against a different search is a 422.
    for index in range(3):
        define_part(client, world, f"R {index}", {"resistance": f"{index + 1}k"})
    first = search(client, {"category_id": str(world.resistors.id), "limit": 2})

    response = client.post(
        f"{CATALOG}/parts/search",
        json={"limit": 2, "cursor": first["next_cursor"]},
    )

    assert response.status_code == 422


# --- Facets ----------------------------------------------------------------------------


def test_facets_come_back_in_the_shape_the_design_draws(client: TestClient, world: World) -> None:
    # Requirement 5.1: each enum option with its count, each boolean's true/false, each
    # number's lowest and highest value, keyed by attribute.
    define_choice(client, world, "mounting", ["smd", "through-hole"])
    client.post(
        f"{CATALOG}/categories/{world.resistors.id}/attributes",
        json={"key": "rohs", "label": "RoHS", "kind": "bool"},
    )
    define_part(client, world, "R 1k", {"resistance": "1k", "mounting": "smd", "rohs": True})
    define_part(client, world, "R 10k", {"resistance": "10k", "mounting": "smd", "rohs": False})

    response = client.get(f"{CATALOG}/categories/{world.resistors.id}/facets")

    assert response.status_code == 200, response.text
    facets = response.json()
    assert facets["enums"]["mounting"] == [
        {"option": "smd", "count": 2},
        {"option": "through-hole", "count": 0},
    ]
    assert facets["bools"]["rohs"] == {"true": 1, "false": 1}
    assert facets["numbers"]["resistance"] == {
        "min": {"value": "1000", "display": "1k"},
        "max": {"value": "10000", "display": "10k"},
    }


def test_a_number_attribute_with_no_values_answers_no_range(
    client: TestClient, world: World
) -> None:
    # Requirement 5.3: no part has a value, so there is no range rather than a failure.
    response = client.get(f"{CATALOG}/categories/{world.resistors.id}/facets")

    assert response.status_code == 200
    assert response.json()["numbers"]["resistance"] is None


def test_facets_count_only_the_parts_matching_text_and_pin(
    client: TestClient, world: World
) -> None:
    # Requirement 5.2: text narrows the counts; the attribute filters never reach facets.
    define_choice(client, world, "mounting", ["smd", "through-hole"])
    define_part(client, world, "Alpha", {"resistance": "1k", "mounting": "smd"})
    define_part(client, world, "Beta", {"resistance": "10k", "mounting": "through-hole"})

    facets_url = f"{CATALOG}/categories/{world.resistors.id}/facets"
    response = client.get(facets_url, params={"q": "Alpha"})

    assert response.status_code == 200
    assert response.json()["enums"]["mounting"] == [
        {"option": "smd", "count": 1},
        {"option": "through-hole", "count": 0},
    ]


def test_both_routes_act_in_the_callers_workspace(client: TestClient, world: World) -> None:
    # ADR 0007's first gate: the unit of work is opened for the caller's bench and no other.
    search(client, {})
    client.get(f"{CATALOG}/categories/{world.resistors.id}/facets")

    assert set(world.catalog.opened_for) == {BENCH}
