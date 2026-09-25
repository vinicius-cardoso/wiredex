"""The catalog routes over the in-memory fakes: a bare FastAPI, no database.

The workspace dependency is a stub, because resolving it is identity's job and the
composition root's wiring (design §3). What is asserted here is the router's own contract:
the status every refusal gets, and the two shapes an attribute value travels in.

The bench is the fakes' *Passives → Resistors* with a required `resistance` in ohms.
"""

from typing import Any

import pytest
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.testclient import TestClient

from support.catalog import BENCH, World
from wiredex.catalog.api.router import create_router
from wiredex.catalog.domain.category import MAX_CATEGORY_DEPTH
from wiredex.catalog.domain.values import WorkspaceId

CATALOG = "/api/catalog"
MADE_UP = "0199aaaa-0000-7000-8000-000000000000"


async def the_bench(_request: Request) -> WorkspaceId:
    """What `bootstrap/app.py` builds from the session: the workspace this request acts in."""
    return BENCH


async def nobody(_request: Request) -> WorkspaceId:
    """A request with no valid session, which identity refuses before the catalog is reached."""
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "log in first")


@pytest.fixture
def world() -> World:
    return World()


@pytest.fixture
def client(world: World) -> TestClient:
    app = FastAPI()
    app.include_router(create_router(world.catalog_use_cases(), the_bench), prefix="/api")
    return TestClient(app)


def defined(client: TestClient, path: str, body: dict[str, Any]) -> dict[str, Any]:
    """POSTs something that is expected to work, so a test can get on with its point."""
    response = client.post(f"{CATALOG}{path}", json=body)
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


def a_resistor(client: TestClient, world: World, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "category_id": str(world.resistors.id),
        "name": "R 4k7 0805",
        "attributes": {"resistance": "4k7"},
    }
    return defined(client, "/parts", body | overrides)


def test_the_tree_comes_out_flat_with_each_category_s_counts(
    client: TestClient, world: World
) -> None:
    # Requirement 1.11: parent, child count and the parts directly under it.
    world.add_part(world.resistors)

    response = client.get(f"{CATALOG}/categories")

    assert response.status_code == 200
    assert [(c["name"], c["child_count"], c["part_count"]) for c in response.json()] == [
        ("Passives", 1, 0),
        ("Resistors", 0, 1),
    ]
    assert response.json()[1]["parent_id"] == str(world.passives.id)


def test_a_category_is_created_at_the_root_or_under_a_parent(
    client: TestClient, world: World
) -> None:
    root = defined(client, "/categories", {"name": "Semiconductors"})
    child = defined(client, "/categories", {"name": "Diodes", "parent_id": root["id"]})

    assert root["parent_id"] is None
    assert child["parent_id"] == root["id"]
    assert len(world.catalog.categories.saved) == 4


def test_one_patch_renames_and_moves_a_category(client: TestClient, world: World) -> None:
    response = client.patch(
        f"{CATALOG}/categories/{world.resistors.id}",
        json={"name": "Fixed resistors", "parent_id": None},
    )

    assert response.status_code == 200
    # parent_id: null is a move to the root, not a field left out.
    assert (response.json()["name"], response.json()["parent_id"]) == ("Fixed resistors", None)


def test_a_patch_that_carries_nothing_is_refused(client: TestClient, world: World) -> None:
    response = client.patch(f"{CATALOG}/categories/{world.resistors.id}", json={})

    assert response.status_code == 422


def test_a_category_still_in_use_is_not_deleted(client: TestClient, world: World) -> None:
    # Requirement 1.9: 409, and the answer says which of the two blocks it.
    blocked = client.delete(f"{CATALOG}/categories/{world.passives.id}")

    assert blocked.status_code == 409
    assert "categories under it" in blocked.json()["detail"]

    world.add_part(world.resistors)
    with_parts = client.delete(f"{CATALOG}/categories/{world.resistors.id}")

    assert with_parts.status_code == 409
    assert "parts" in with_parts.json()["detail"]


def test_an_empty_category_is_deleted(client: TestClient, world: World) -> None:
    empty = defined(client, "/categories", {"name": "Inductors"})

    assert client.delete(f"{CATALOG}/categories/{empty['id']}").status_code == 204
    assert len(world.catalog.categories.saved) == 2


def test_a_schema_carries_the_ancestors_fields_and_marks_them(
    client: TestClient, world: World
) -> None:
    # Requirement 2.7: ancestors first, each field marked with where it comes from.
    defined(
        client,
        f"/categories/{world.passives.id}/attributes",
        {
            "key": "mounting",
            "label": "Mounting",
            "kind": "enum",
            "options": ["smd", "through-hole"],
        },
    )

    response = client.get(f"{CATALOG}/categories/{world.resistors.id}/schema")

    assert response.status_code == 200
    body = response.json()
    assert body["category"]["name"] == "Resistors"
    assert [(a["key"], a["inherited"]) for a in body["attributes"]] == [
        ("mounting", True),
        ("resistance", False),
    ]


def test_an_attribute_is_defined_and_then_edited(client: TestClient, world: World) -> None:
    created = defined(
        client,
        f"/categories/{world.resistors.id}/attributes",
        {
            "key": "tolerance",
            "label": "Tolerance",
            "kind": "enum",
            "options": ["1%", "5%"],
            "position": 2,
        },
    )

    assert (created["kind"], created["required"], created["unit"]) == ("enum", False, None)

    response = client.patch(
        f"{CATALOG}/attributes/{created['id']}", json={"label": "Tolerance (%)", "required": True}
    )

    assert response.status_code == 200
    assert (response.json()["label"], response.json()["required"]) == ("Tolerance (%)", True)
    assert response.json()["options"] == ["1%", "5%"]


@pytest.mark.parametrize(
    "change", [{"key": "resistance_ohm"}, {"kind": "text"}], ids=["key", "kind"]
)
def test_an_attributes_key_and_kind_cannot_change(
    client: TestClient, world: World, change: dict[str, str]
) -> None:
    # Requirement 2.9: 422, and the answer says what to do instead.
    response = client.patch(f"{CATALOG}/attributes/{world.resistance.id}", json=change)

    assert response.status_code == 422
    assert "define a new one" in response.json()["detail"]


def test_a_removed_attribute_keeps_its_values_and_flags_the_part(
    client: TestClient, world: World
) -> None:
    # Requirements 2.10 and 5.2: the value stays, visible, and the part still reads.
    part = a_resistor(client, world)

    assert client.delete(f"{CATALOG}/attributes/{world.resistance.id}").status_code == 204

    response = client.get(f"{CATALOG}/parts/{part['id']}")
    body = response.json()

    assert response.status_code == 200
    assert body["needs_review"] is True
    assert [(p["key"], p["problem"]) for p in body["problems"]] == [("resistance", "unknown_key")]
    # Kept, and with no unit left to label it by.
    assert body["attributes"]["resistance"] == {
        "value": "4700",
        "display": "4.7k",
        "unit": None,
    }


def test_a_number_is_typed_as_printed_and_read_back_in_three_forms(
    client: TestClient, world: World
) -> None:
    # Requirements 3.3, 3.9: 4k7 goes in, the exact value and 4.7k come back.
    part = a_resistor(client, world, attributes={"resistance": "4k7"})

    assert part["attributes"]["resistance"] == {
        "value": "4700",
        "display": "4.7k",
        "unit": "Ω",
    }
    assert (part["needs_review"], part["problems"]) == (False, [])

    read = client.get(f"{CATALOG}/parts/{part['id']}")

    assert read.json()["attributes"] == part["attributes"]


def test_every_kind_of_value_comes_back_as_it_is_stored(client: TestClient, world: World) -> None:
    for body in (
        {"key": "tolerance", "label": "Tolerance", "kind": "enum", "options": ["1%", "5%"]},
        {"key": "notes", "label": "Notes", "kind": "text"},
        {"key": "pulse_rated", "label": "Pulse rated", "kind": "bool"},
    ):
        defined(client, f"/categories/{world.resistors.id}/attributes", body)

    part = a_resistor(
        client,
        world,
        attributes={
            "resistance": "4k7",
            "tolerance": "1%",
            "notes": " bin 3 ",
            "pulse_rated": True,
        },
    )

    assert part["attributes"]["tolerance"] == {"value": "1%", "display": "1%", "unit": None}
    # Trimmed by the text validator, and a real boolean stays one.
    assert part["attributes"]["notes"] == {"value": "bin 3", "display": "bin 3", "unit": None}
    assert part["attributes"]["pulse_rated"] == {
        "value": True,
        "display": "true",
        "unit": None,
    }


def test_the_part_list_narrows_by_name_and_carries_a_cursor(
    client: TestClient, world: World
) -> None:
    for name in ("R 4k7 0805", "R 10k 0805", "R 100R 0805"):
        a_resistor(client, world, name=name)

    page = client.get(f"{CATALOG}/parts", params={"limit": 2}).json()

    assert len(page["items"]) == 2
    assert page["next_cursor"] is not None
    # The summary carries no attribute values: a page resolves no schemas (requirement 8.2).
    assert "attributes" not in page["items"][0]

    rest = client.get(f"{CATALOG}/parts", params={"limit": 2, "cursor": page["next_cursor"]}).json()

    assert len(rest["items"]) == 1
    assert rest["next_cursor"] is None

    searched = client.get(f"{CATALOG}/parts", params={"q": "10K"}).json()

    assert [part["name"] for part in searched["items"]] == ["R 10k 0805"]


def test_a_part_is_updated_moved_and_deleted(client: TestClient, world: World) -> None:
    part = a_resistor(client, world)
    thick_film = defined(
        client, "/categories", {"name": "Thick film", "parent_id": str(world.resistors.id)}
    )

    response = client.patch(
        f"{CATALOG}/parts/{part['id']}",
        json={
            "name": "R 10k 0805",
            "attributes": {"resistance": "10k"},
            "category_id": thick_film["id"],
            "mpn": "RC0805",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert (body["name"], body["mpn"]) == ("R 10k 0805", "RC0805")
    assert body["category_id"] == thick_film["id"]
    assert body["attributes"]["resistance"]["display"] == "10k"

    assert client.delete(f"{CATALOG}/parts/{part['id']}").status_code == 204
    assert client.get(f"{CATALOG}/parts/{part['id']}").status_code == 404


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", f"/categories/{MADE_UP}/schema"),
        ("PATCH", f"/categories/{MADE_UP}"),
        ("DELETE", f"/categories/{MADE_UP}"),
        ("POST", f"/categories/{MADE_UP}/attributes"),
        ("PATCH", f"/attributes/{MADE_UP}"),
        ("DELETE", f"/attributes/{MADE_UP}"),
        ("GET", f"/parts/{MADE_UP}"),
        ("PATCH", f"/parts/{MADE_UP}"),
        ("DELETE", f"/parts/{MADE_UP}"),
    ],
)
def test_an_id_this_workspace_does_not_hold_is_simply_not_found(
    client: TestClient, method: str, path: str
) -> None:
    # Requirement 6.4: another workspace's id is 404, never 403, so ids stay unguessable.
    body = {
        "name": "Anything",
        "key": "anything",
        "label": "Anything",
        "kind": "text",
        "attributes": {},
    }

    response = client.request(method, f"{CATALOG}{path}", json=body)

    assert response.status_code == 404, response.text


def test_a_sibling_name_already_taken_is_a_conflict(client: TestClient, world: World) -> None:
    # Requirement 1.3, at the root too: two roots are siblings of each other.
    under_passives = client.post(
        f"{CATALOG}/categories", json={"name": "Resistors", "parent_id": str(world.passives.id)}
    )
    at_the_root = client.post(f"{CATALOG}/categories", json={"name": "Passives"})

    assert (under_passives.status_code, at_the_root.status_code) == (409, 409)
    assert "already a" in under_passives.json()["detail"]


def test_a_key_defined_here_or_above_is_a_conflict(client: TestClient, world: World) -> None:
    # Requirements 2.5 and 2.6, and the answer says which of the two it is.
    here = client.post(
        f"{CATALOG}/categories/{world.resistors.id}/attributes",
        json={"key": "resistance", "label": "Resistance", "kind": "number"},
    )

    assert here.status_code == 409
    assert "already defined here" in here.json()["detail"]

    defined(
        client,
        f"/categories/{world.passives.id}/attributes",
        {"key": "mounting", "label": "Mounting", "kind": "text"},
    )
    inherited = client.post(
        f"{CATALOG}/categories/{world.resistors.id}/attributes",
        json={"key": "mounting", "label": "Mounting", "kind": "text"},
    )

    assert inherited.status_code == 409
    assert "above this one" in inherited.json()["detail"]


def test_an_mpn_another_part_uses_is_a_conflict(client: TestClient, world: World) -> None:
    # Requirement 4.6, folded: TI/BME280 meets ti/bme280.
    a_resistor(client, world, manufacturer="Yageo", mpn="RC0805FR-074K7L")

    response = client.post(
        f"{CATALOG}/parts",
        json={
            "category_id": str(world.resistors.id),
            "name": "Clone",
            "attributes": {"resistance": "4k7"},
            "manufacturer": "yageo",
            "mpn": "rc0805fr-074k7l",
        },
    )

    assert response.status_code == 409
    assert "already used by" in response.json()["detail"]


@pytest.mark.parametrize(
    ("typed", "message"),
    [
        pytest.param({}, "resistance is required", id="a required value missing"),
        pytest.param({"resistance": "4K7"}, "K is kelvin", id="kelvin where kilo was meant"),
        pytest.param({"resistance": "nope"}, "not a number", id="not a number at all"),
        pytest.param({"resistance": "4k7", "resistence": "4k7"}, "not an attribute", id="a typo"),
        pytest.param({"resistance": True}, "takes a number", id="a switch where a number goes"),
    ],
)
def test_a_value_the_schema_refuses_answers_422_and_names_the_attribute(
    client: TestClient, world: World, typed: dict[str, Any], message: str
) -> None:
    # Requirements 3.7, 3.8, 4.2 to 4.5: the answer names the attribute, for the field.
    response = client.post(
        f"{CATALOG}/parts",
        json={"category_id": str(world.resistors.id), "name": "R 4k7", "attributes": typed},
    )

    assert response.status_code == 422
    assert message in response.json()["detail"]
    assert world.catalog.parts.saved == {}


def test_a_string_is_not_a_boolean(client: TestClient, world: World) -> None:
    # Requirement 4.5: the client sends JSON, so "true" is a string and a mistake.
    defined(
        client,
        f"/categories/{world.resistors.id}/attributes",
        {"key": "pulse_rated", "label": "Pulse rated", "kind": "bool"},
    )

    response = client.post(
        f"{CATALOG}/parts",
        json={
            "category_id": str(world.resistors.id),
            "name": "R 4k7",
            "attributes": {"resistance": "4k7", "pulse_rated": "true"},
        },
    )

    assert response.status_code == 422
    assert "takes true or false" in response.json()["detail"]


def test_a_choice_with_nothing_to_choose_from_is_refused(client: TestClient, world: World) -> None:
    # Requirement 2.3.
    response = client.post(
        f"{CATALOG}/categories/{world.resistors.id}/attributes",
        json={"key": "tolerance", "label": "Tolerance", "kind": "enum", "options": []},
    )

    assert response.status_code == 422
    assert "needs some options" in response.json()["detail"]


def test_a_key_that_is_not_a_slug_is_refused(client: TestClient, world: World) -> None:
    # Requirement 2.4: the key names a JSONB field, so it stays a slug.
    response = client.post(
        f"{CATALOG}/categories/{world.resistors.id}/attributes",
        json={"key": "Resistance (Ω)", "label": "Resistance", "kind": "number"},
    )

    assert response.status_code == 422
    assert "is not a key like resistance" in response.json()["detail"]


def test_a_category_cannot_move_under_its_own_descendant(client: TestClient, world: World) -> None:
    # Requirement 1.5.
    response = client.patch(
        f"{CATALOG}/categories/{world.passives.id}", json={"parent_id": str(world.resistors.id)}
    )

    assert response.status_code == 422
    assert "under itself" in response.json()["detail"]
    assert world.passives.parent_id is None


def test_a_category_past_the_depth_cap_is_refused(client: TestClient, world: World) -> None:
    # Requirement 1.4, and the answer names the limit.
    deepest = world.resistors
    for level in range(3, MAX_CATEGORY_DEPTH + 1):
        deepest = world.add_category(f"Level {level}", deepest)

    response = client.post(
        f"{CATALOG}/categories", json={"name": "One too deep", "parent_id": str(deepest.id)}
    )

    assert response.status_code == 422
    assert str(MAX_CATEGORY_DEPTH) in response.json()["detail"]


def test_a_request_with_no_session_never_reaches_the_catalog(world: World) -> None:
    # Requirement 6.2: identity refuses first, so no use case runs.
    app = FastAPI()
    app.include_router(create_router(world.catalog_use_cases(), nobody), prefix="/api")
    logged_out = TestClient(app)

    response = logged_out.get(f"{CATALOG}/categories")

    assert response.status_code == 401
    assert world.catalog.opened_for == []
