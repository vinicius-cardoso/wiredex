"""The inventory routes over the in-memory fakes: a bare FastAPI, no database.

The workspace dependency is a stub, because resolving it is identity's job and the
composition root's wiring (design §3). What is asserted here is the router's own contract:
the status every refusal in the design's table gets, and the balances a movement answers
with, so the web can update in place.

The bench is the fakes' *Lab → Drawer 3*, with a lot-counted part and a unit-tracked one.
"""

from typing import Any

import pytest
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.testclient import TestClient

from support.inventory import (
    BENCH,
    CONSUMABLE_PART,
    LOT_COUNTED_PART,
    UNIT_TRACKED_PART,
    World,
)
from wiredex.inventory.api.router import create_router
from wiredex.inventory.domain.values import WorkspaceId

INVENTORY = "/api/inventory"
MADE_UP = "0199aaaa-0000-7000-8000-000000000000"


async def the_bench(_request: Request) -> WorkspaceId:
    """What `bootstrap/app.py` builds from the session: the workspace this request acts in."""
    return BENCH


async def nobody(_request: Request) -> WorkspaceId:
    """A request with no valid session, which identity refuses before inventory is reached."""
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "log in first")


@pytest.fixture
def world() -> World:
    return World()


@pytest.fixture
def client(world: World) -> TestClient:
    app = FastAPI()
    app.include_router(create_router(world.inventory_use_cases(), the_bench), prefix="/api")
    return TestClient(app)


def created(client: TestClient, path: str, body: dict[str, Any]) -> dict[str, Any]:
    """POSTs something that is expected to work, so a test can get on with its point."""
    response = client.post(f"{INVENTORY}{path}", json=body)
    assert response.status_code == 201, response.text
    body_out: dict[str, Any] = response.json()
    return body_out


# --- Locations ----------------------------------------------------------------------------


def test_the_tree_comes_out_flat_with_each_location_s_counts(
    client: TestClient, world: World
) -> None:
    # Requirement 1.12: parent, short code, child count and lot count.
    world.hold_lot(LOT_COUNTED_PART, world.drawer, on_hand=5)

    response = client.get(f"{INVENTORY}/locations")

    assert response.status_code == 200
    tree = {loc["name"]: loc for loc in response.json()}
    assert tree["Lab"]["child_count"] == 1
    assert tree["Lab"]["parent_id"] is None
    assert tree["Drawer 3"]["parent_id"] == str(world.lab.id)
    assert tree["Drawer 3"]["lot_count"] == 1
    assert tree["Lab"]["code"].startswith("WX-L-")


def test_a_location_is_created_at_the_root_or_under_a_parent(client: TestClient) -> None:
    root = created(client, "/locations", {"name": "Workshop"})
    child = created(client, "/locations", {"name": "Shelf A", "parent_id": root["id"]})

    assert root["parent_id"] is None
    # A short code is minted at creation (requirement 2.1).
    assert root["code"].startswith("WX-L-")
    assert child["parent_id"] == root["id"]


def test_one_patch_renames_and_moves_a_location(client: TestClient, world: World) -> None:
    response = client.patch(
        f"{INVENTORY}/locations/{world.drawer.id}",
        json={"name": "Drawer 4", "parent_id": None},
    )

    assert response.status_code == 200
    # parent_id: null is a move to the root, not a field left out; the code is kept (1.8).
    assert (response.json()["name"], response.json()["parent_id"]) == ("Drawer 4", None)
    assert response.json()["code"] == str(world.drawer.code)


def test_a_patch_that_carries_nothing_is_refused(client: TestClient, world: World) -> None:
    response = client.patch(f"{INVENTORY}/locations/{world.drawer.id}", json={})

    assert response.status_code == 422


def test_a_duplicate_sibling_name_is_a_conflict(client: TestClient, world: World) -> None:
    # Requirement 1.3: two children of Lab can't share a name.
    response = client.post(
        f"{INVENTORY}/locations",
        json={"name": "Drawer 3", "parent_id": str(world.lab.id)},
    )

    assert response.status_code == 409


def test_deleting_a_location_that_holds_lots_is_a_conflict(
    client: TestClient, world: World
) -> None:
    # Requirement 1.10: a location holding stock can't be deleted.
    world.hold_lot(LOT_COUNTED_PART, world.drawer, on_hand=3)

    response = client.delete(f"{INVENTORY}/locations/{world.drawer.id}")

    assert response.status_code == 409


def test_deleting_a_location_with_children_is_a_conflict(client: TestClient, world: World) -> None:
    response = client.delete(f"{INVENTORY}/locations/{world.lab.id}")

    assert response.status_code == 409


def test_deleting_an_empty_location_answers_no_content(client: TestClient, world: World) -> None:
    response = client.delete(f"{INVENTORY}/locations/{world.drawer.id}")

    assert response.status_code == 204


def test_an_unknown_location_is_not_found(client: TestClient) -> None:
    response = client.patch(f"{INVENTORY}/locations/{MADE_UP}", json={"name": "Nowhere"})

    assert response.status_code == 404


# --- Movements ----------------------------------------------------------------------------


def test_receiving_stock_answers_the_new_balance(client: TestClient, world: World) -> None:
    # Requirement 4.1: a RECEIVE raises on_hand and answers the balance.
    response = client.post(
        f"{INVENTORY}/receive",
        json={
            "part_id": str(LOT_COUNTED_PART),
            "location_id": str(world.drawer.id),
            "quantity": 40,
        },
    )

    assert response.status_code == 201, response.text
    balance = response.json()
    assert balance["on_hand"] == 40
    assert balance["reserved"] == 0
    assert balance["available"] == 40


def test_receiving_an_unknown_part_is_not_found(client: TestClient, world: World) -> None:
    # Requirement 4.2: a part the catalog doesn't know is a 404.
    response = client.post(
        f"{INVENTORY}/receive",
        json={"part_id": MADE_UP, "location_id": str(world.drawer.id), "quantity": 1},
    )

    assert response.status_code == 404


def test_receiving_a_unit_tracked_part_is_refused(client: TestClient, world: World) -> None:
    # Requirement 6.3: a lot receive into a unit-tracked part is a 422.
    response = client.post(
        f"{INVENTORY}/receive",
        json={
            "part_id": str(UNIT_TRACKED_PART),
            "location_id": str(world.drawer.id),
            "quantity": 1,
        },
    )

    assert response.status_code == 422


def test_receiving_a_consumable_is_refused_saying_why(client: TestClient, world: World) -> None:
    # 09's requirement 2.1: NotStockedError falls through the router's table to 422.
    response = client.post(
        f"{INVENTORY}/receive",
        json={"part_id": str(CONSUMABLE_PART), "location_id": str(world.drawer.id), "quantity": 1},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "this part's category isn't stocked, so none of it is received"
    )


def test_recounting_a_consumable_where_it_has_no_lot_is_refused(
    client: TestClient, world: World
) -> None:
    # 09's requirement 2.2.
    response = client.post(
        f"{INVENTORY}/adjust",
        json={
            "part_id": str(CONSUMABLE_PART),
            "location_id": str(world.drawer.id),
            "counted": 3,
            "reason": "recount",
        },
    )

    assert response.status_code == 422
    assert "isn't stocked" in response.json()["detail"]


def test_a_non_positive_receive_is_refused_by_validation(client: TestClient, world: World) -> None:
    response = client.post(
        f"{INVENTORY}/receive",
        json={"part_id": str(LOT_COUNTED_PART), "location_id": str(world.drawer.id), "quantity": 0},
    )

    assert response.status_code == 422


def test_adjusting_to_a_count_answers_the_new_balance(client: TestClient, world: World) -> None:
    # Requirement 4.3: an ADJUST sets on_hand to the absolute counted quantity.
    world.hold_lot(LOT_COUNTED_PART, world.drawer, on_hand=10)

    response = client.post(
        f"{INVENTORY}/adjust",
        json={
            "part_id": str(LOT_COUNTED_PART),
            "location_id": str(world.drawer.id),
            "counted": 7,
            "reason": "recount",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["on_hand"] == 7


def test_an_unknown_adjust_reason_is_refused_by_validation(
    client: TestClient, world: World
) -> None:
    response = client.post(
        f"{INVENTORY}/adjust",
        json={
            "part_id": str(LOT_COUNTED_PART),
            "location_id": str(world.drawer.id),
            "counted": 1,
            "reason": "vanished",
        },
    )

    assert response.status_code == 422


def test_moving_stock_answers_both_lots_balances(client: TestClient, world: World) -> None:
    # Requirement 4.5: a move answers the source and destination balances.
    other = world.add_location("Bin 1", world.lab)
    world.hold_lot(LOT_COUNTED_PART, world.drawer, on_hand=50)

    response = client.post(
        f"{INVENTORY}/move",
        json={
            "part_id": str(LOT_COUNTED_PART),
            "from_location_id": str(world.drawer.id),
            "to_location_id": str(other.id),
            "quantity": 20,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source"]["on_hand"] == 30
    assert body["destination"]["on_hand"] == 20


def test_moving_more_than_the_source_holds_is_a_conflict(client: TestClient, world: World) -> None:
    # Requirement 4.7: an over-draw is a 409, and writes nothing.
    other = world.add_location("Bin 2", world.lab)
    world.hold_lot(LOT_COUNTED_PART, world.drawer, on_hand=5)

    response = client.post(
        f"{INVENTORY}/move",
        json={
            "part_id": str(LOT_COUNTED_PART),
            "from_location_id": str(world.drawer.id),
            "to_location_id": str(other.id),
            "quantity": 10,
        },
    )

    assert response.status_code == 409


def test_moving_to_the_same_location_is_refused(client: TestClient, world: World) -> None:
    # Requirement 4.8: source and destination must differ, a 422.
    world.hold_lot(LOT_COUNTED_PART, world.drawer, on_hand=5)

    response = client.post(
        f"{INVENTORY}/move",
        json={
            "part_id": str(LOT_COUNTED_PART),
            "from_location_id": str(world.drawer.id),
            "to_location_id": str(world.drawer.id),
            "quantity": 1,
        },
    )

    assert response.status_code == 422


# --- Stock per part -----------------------------------------------------------------------


def test_a_part_s_stock_totals_and_breaks_down_by_location(
    client: TestClient, world: World
) -> None:
    # Requirement 7.3: total on_hand and a per-location breakdown, each with its location.
    bin_one = world.add_location("Bin 3", world.lab)
    world.hold_lot(LOT_COUNTED_PART, world.drawer, on_hand=150)
    world.hold_lot(LOT_COUNTED_PART, bin_one, on_hand=30)

    response = client.get(f"{INVENTORY}/parts/{LOT_COUNTED_PART}/stock")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 180
    on_hand_by_code = {row["location"]["code"]: row["on_hand"] for row in body["breakdown"]}
    assert sum(on_hand_by_code.values()) == 180
    assert len(body["breakdown"]) == 2


def test_a_part_s_stock_answers_reserved_and_available_per_location_and_in_total(
    client: TestClient, world: World
) -> None:
    # Requirement 10.3: on hand, reserved and available, per location and in total; available
    # is on hand less reserved.
    bin_one = world.add_location("Bin 4", world.lab)
    world.hold_lot(LOT_COUNTED_PART, world.drawer, on_hand=150, reserved=40)
    world.hold_lot(LOT_COUNTED_PART, bin_one, on_hand=30, reserved=0)

    response = client.get(f"{INVENTORY}/parts/{LOT_COUNTED_PART}/stock")

    assert response.status_code == 200
    body = response.json()
    assert (body["total"], body["reserved"], body["available"]) == (180, 40, 140)
    by_code = {row["location"]["code"]: row for row in body["breakdown"]}
    drawer = by_code[str(world.drawer.code)]
    assert (drawer["on_hand"], drawer["reserved"], drawer["available"]) == (150, 40, 110)
    bin_row = by_code[str(bin_one.code)]
    assert (bin_row["on_hand"], bin_row["reserved"], bin_row["available"]) == (30, 0, 30)


def test_a_part_never_received_reads_zero_and_empty(client: TestClient) -> None:
    # Requirement 7.4: never received is zeros and an empty breakdown, not a 404.
    response = client.get(f"{INVENTORY}/parts/{MADE_UP}/stock")

    assert response.status_code == 200
    assert response.json() == {"total": 0, "reserved": 0, "available": 0, "breakdown": []}


def test_a_batch_totals_a_page_of_parts_in_one_call(client: TestClient, world: World) -> None:
    # Requirements 7.1, 7.2: the parts list asks totals for a page of ids at once.
    world.hold_lot(LOT_COUNTED_PART, world.drawer, on_hand=12)

    response = client.get(
        f"{INVENTORY}/parts/stock",
        params={"part_id": [str(LOT_COUNTED_PART), MADE_UP]},
    )

    assert response.status_code == 200
    totals = {row["part_id"]: row["on_hand"] for row in response.json()}
    # A part with no stock is simply absent; the list reads that as zero.
    assert totals == {str(LOT_COUNTED_PART): 12}
