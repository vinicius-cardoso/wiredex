"""The unit routes over the in-memory fakes: a bare FastAPI, no database.

The workspace dependency is a stub, because resolving it is identity's job and the
composition root's wiring (design §3). What is asserted here is the router's own contract:
the receive answer carrying the created units and the lot balance, each read row carrying its
location, and the status every refusal in the design's table gets.

The bench is the fakes' *Lab → Drawer 3*, with a lot-counted part and a unit-tracked one.
"""

from datetime import timedelta
from typing import Any, get_args

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from support.inventory import (
    BENCH,
    LOT_COUNTED_PART,
    TRACKED_CONSUMABLE_PART,
    UNIT_TRACKED_PART,
    World,
)
from wiredex.inventory.api.router import create_router
from wiredex.inventory.api.schemas import RetireReasonName, UnitStatusName
from wiredex.inventory.domain.unit import UnitStatus
from wiredex.inventory.domain.values import MovementReason, Serial, WorkspaceId

INVENTORY = "/api/inventory"
MADE_UP = "0199aaaa-0000-7000-8000-000000000000"


async def the_bench(_request: Request) -> WorkspaceId:
    """What `bootstrap/app.py` builds from the session: the workspace this request acts in."""
    return BENCH


@pytest.fixture
def world() -> World:
    return World()


@pytest.fixture
def client(world: World) -> TestClient:
    app = FastAPI()
    app.include_router(create_router(world.inventory_use_cases(), the_bench), prefix="/api")
    return TestClient(app)


def receive(client: TestClient, body: dict[str, Any]) -> dict[str, Any]:
    """Receives units expected to work, so a test can get on with its point."""
    response = client.post(f"{INVENTORY}/units", json=body)
    assert response.status_code == 201, response.text
    out: dict[str, Any] = response.json()
    return out


# --- Receiving ----------------------------------------------------------------------------


def test_receiving_units_answers_the_units_and_the_lot_balance(
    client: TestClient, world: World
) -> None:
    # Requirement 1.1: N entries create N units, each with its own code, on one lot.
    body = receive(
        client,
        {
            "part_id": str(UNIT_TRACKED_PART),
            "location_id": str(world.drawer.id),
            "units": [{"serial": "SN-1"}, {"mac": "AA-BB-CC-DD-EE-FF"}, {}],
        },
    )

    codes = [unit["code"] for unit in body["units"]]
    assert codes == ["WX-U-0001", "WX-U-0002", "WX-U-0003"]
    # The receive answer carries the lot balance, so the web needs no refetch.
    assert body["balance"]["on_hand"] == 3
    # Each unit carries its resolved location (the drawer it landed in) and its part's name.
    assert {unit["location"]["id"] for unit in body["units"]} == {str(world.drawer.id)}
    assert {unit["part_name"] for unit in body["units"]} == {"ESP32 DevKit"}
    # The MAC comes back canonical, whatever spelling it was received in.
    assert body["units"][1]["mac"] == "aa:bb:cc:dd:ee:ff"
    assert body["units"][0]["serial"] == "SN-1"
    assert body["units"][2]["serial"] is None


def test_receiving_an_unknown_part_is_not_found(client: TestClient, world: World) -> None:
    # Requirement 1.3: a part the catalog doesn't know is a 404, and creates nothing.
    response = client.post(
        f"{INVENTORY}/units",
        json={"part_id": MADE_UP, "location_id": str(world.drawer.id), "units": [{}]},
    )

    assert response.status_code == 404


def test_receiving_units_of_a_consumable_is_refused_saying_why(
    client: TestClient, world: World
) -> None:
    # 09's requirements 2.1 and 2.4: a tracked consumable is refused as not stocked.
    response = client.post(
        f"{INVENTORY}/units",
        json={
            "part_id": str(TRACKED_CONSUMABLE_PART),
            "location_id": str(world.drawer.id),
            "units": [{}],
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "this part's category isn't stocked, so none of it is received"
    )


def test_receiving_a_lot_counted_part_as_units_is_refused(client: TestClient, world: World) -> None:
    # Requirement 1.5: a unit receive into a lot-counted part is a 422.
    response = client.post(
        f"{INVENTORY}/units",
        json={"part_id": str(LOT_COUNTED_PART), "location_id": str(world.drawer.id), "units": [{}]},
    )

    assert response.status_code == 422
    assert "lots" in response.json()["detail"]


def test_a_receipt_with_no_units_is_refused_by_validation(client: TestClient, world: World) -> None:
    # An empty receipt is nothing to do; the body demands at least one unit.
    response = client.post(
        f"{INVENTORY}/units",
        json={"part_id": str(UNIT_TRACKED_PART), "location_id": str(world.drawer.id), "units": []},
    )

    assert response.status_code == 422


def test_a_receipt_of_more_than_a_hundred_units_is_refused(
    client: TestClient, world: World
) -> None:
    response = client.post(
        f"{INVENTORY}/units",
        json={
            "part_id": str(UNIT_TRACKED_PART),
            "location_id": str(world.drawer.id),
            "units": [{}] * 101,
        },
    )

    assert response.status_code == 422


def test_a_malformed_mac_is_refused_by_validation(client: TestClient, world: World) -> None:
    # Requirement 5.4: a MAC that isn't six hex octets is a 422.
    response = client.post(
        f"{INVENTORY}/units",
        json={
            "part_id": str(UNIT_TRACKED_PART),
            "location_id": str(world.drawer.id),
            "units": [{"mac": "not-a-mac"}],
        },
    )

    assert response.status_code == 422


def test_a_duplicate_mac_across_units_is_a_conflict(client: TestClient, world: World) -> None:
    # Requirement 5.2: a second unit can't take a MAC another already holds.
    receive(
        client,
        {
            "part_id": str(UNIT_TRACKED_PART),
            "location_id": str(world.drawer.id),
            "units": [{"mac": "aa:bb:cc:dd:ee:ff"}],
        },
    )

    response = client.post(
        f"{INVENTORY}/units",
        json={
            "part_id": str(UNIT_TRACKED_PART),
            "location_id": str(world.drawer.id),
            "units": [{"mac": "AA:BB:CC:DD:EE:FF"}],
        },
    )

    assert response.status_code == 409


# --- Reads and search ---------------------------------------------------------------------


def test_a_parts_units_come_out_with_their_location(client: TestClient, world: World) -> None:
    # Requirement 6.1: a part's units, each with code, serial, MAC, status and location.
    lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=1)
    unit = world.hold_unit(UNIT_TRACKED_PART, lot, serial=Serial("SN-42"))

    response = client.get(f"{INVENTORY}/parts/{UNIT_TRACKED_PART}/units")

    assert response.status_code == 200
    rows = response.json()
    assert [row["id"] for row in rows] == [str(unit.id)]
    assert rows[0]["location"]["id"] == str(world.drawer.id)
    assert rows[0]["status"] == "in_stock"


def test_a_locations_units_come_out(client: TestClient, world: World) -> None:
    # Requirement 6.2: the units sitting in a location.
    lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=1)
    unit = world.hold_unit(UNIT_TRACKED_PART, lot)

    response = client.get(f"{INVENTORY}/locations/{world.drawer.id}/units")

    assert response.status_code == 200
    assert [row["id"] for row in response.json()] == [str(unit.id)]


def test_the_search_matches_a_mac_substring_and_carries_the_location(
    client: TestClient, world: World
) -> None:
    # Requirement 6.3: the term matches code/serial/MAC, each row with part, location, status.
    body = receive(
        client,
        {
            "part_id": str(UNIT_TRACKED_PART),
            "location_id": str(world.drawer.id),
            "units": [{"mac": "aa:bb:cc:dd:ee:ff"}],
        },
    )

    response = client.get(f"{INVENTORY}/units", params={"search": "cc:dd"})

    assert response.status_code == 200
    rows = response.json()
    assert [row["id"] for row in rows] == [body["units"][0]["id"]]
    assert rows[0]["location"]["id"] == str(world.drawer.id)


def test_an_empty_search_lists_every_unit_newest_first_with_its_part(
    client: TestClient, world: World
) -> None:
    # The boards list: nothing typed lists the bench's units, the last received first, each
    # row naming its part.
    lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=2)
    older = world.hold_unit(UNIT_TRACKED_PART, lot)
    world.clock.advance(timedelta(minutes=1))
    newer = world.hold_unit(UNIT_TRACKED_PART, lot)

    for params in ({}, {"search": "   "}):
        response = client.get(f"{INVENTORY}/units", params=params)

        assert response.status_code == 200
        rows = response.json()
        assert [row["id"] for row in rows] == [str(newer.id), str(older.id)]
        assert {row["part_name"] for row in rows} == {"ESP32 DevKit"}
    # One read of the names for the whole list, not one per row.
    assert world.parts.name_reads == [frozenset({UNIT_TRACKED_PART})] * 2


def test_the_list_narrows_by_status_and_by_part(client: TestClient, world: World) -> None:
    boards = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=1)
    old_boards = world.hold_lot(TRACKED_CONSUMABLE_PART, world.drawer, on_hand=1)
    world.hold_unit(UNIT_TRACKED_PART, boards)
    retired = world.hold_unit(UNIT_TRACKED_PART, boards, status=UnitStatus.RETIRED)
    other = world.hold_unit(TRACKED_CONSUMABLE_PART, old_boards)

    by_status = client.get(f"{INVENTORY}/units", params={"status": "retired"})
    by_part = client.get(f"{INVENTORY}/units", params={"part_id": str(TRACKED_CONSUMABLE_PART)})

    assert [row["id"] for row in by_status.json()] == [str(retired.id)]
    assert [row["id"] for row in by_part.json()] == [str(other.id)]
    assert by_part.json()[0]["part_name"] == "Old dev board"


@pytest.mark.parametrize(
    "params",
    [
        {"status": "lost"},
        {"part_id": "not-a-part"},
        {"search": "x" * 101},
    ],
)
def test_a_filter_the_list_doesnt_know_is_refused(
    client: TestClient, params: dict[str, str]
) -> None:
    response = client.get(f"{INVENTORY}/units", params=params)

    assert response.status_code == 422


def test_the_boards_parts_come_out_with_their_counts_by_name(
    client: TestClient, world: World
) -> None:
    # Declared before `/units/{unit_id}`, so "parts" is never read as a unit id (a 422).
    boards = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=1)
    old_boards = world.hold_lot(TRACKED_CONSUMABLE_PART, world.drawer, on_hand=1)
    world.hold_unit(UNIT_TRACKED_PART, boards)
    world.hold_unit(UNIT_TRACKED_PART, boards, status=UnitStatus.RETIRED)
    world.hold_unit(TRACKED_CONSUMABLE_PART, old_boards)
    del world.parts.named[TRACKED_CONSUMABLE_PART]

    response = client.get(f"{INVENTORY}/units/parts")

    assert response.status_code == 200
    assert response.json() == [
        {"part_id": str(UNIT_TRACKED_PART), "part_name": "ESP32 DevKit", "units": 2},
        {"part_id": str(TRACKED_CONSUMABLE_PART), "part_name": None, "units": 1},
    ]


def test_a_bench_with_no_boards_offers_no_parts(client: TestClient) -> None:
    response = client.get(f"{INVENTORY}/units/parts")

    assert response.status_code == 200
    assert response.json() == []


def test_one_unit_is_read_by_id(client: TestClient, world: World) -> None:
    lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=1)
    unit = world.hold_unit(UNIT_TRACKED_PART, lot)

    response = client.get(f"{INVENTORY}/units/{unit.id}")

    assert response.status_code == 200
    assert response.json()["code"] == str(unit.code)
    assert response.json()["location"]["id"] == str(world.drawer.id)
    assert response.json()["part_name"] == "ESP32 DevKit"


def test_a_unit_of_a_part_the_catalog_no_longer_holds_answers_no_part_name(
    client: TestClient, world: World
) -> None:
    lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=1)
    unit = world.hold_unit(UNIT_TRACKED_PART, lot)
    del world.parts.named[UNIT_TRACKED_PART]

    response = client.get(f"{INVENTORY}/units/{unit.id}")

    assert response.status_code == 200
    assert response.json()["part_name"] is None


def test_an_unknown_unit_is_not_found(client: TestClient) -> None:
    # Requirement 7.2: a unit this workspace doesn't hold is a 404, not a 403.
    response = client.get(f"{INVENTORY}/units/{MADE_UP}")

    assert response.status_code == 404


def test_an_in_stock_unit_answers_no_revision(client: TestClient, world: World) -> None:
    # Requirement 3.10: a unit answers the revision it is held by, null when it holds none.
    lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=1)
    unit = world.hold_unit(UNIT_TRACKED_PART, lot)

    response = client.get(f"{INVENTORY}/units/{unit.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["revision_id"] is None
    assert body["location"]["id"] == str(world.drawer.id)


@pytest.mark.parametrize("held", [UnitStatus.RESERVED, UnitStatus.IN_USE])
def test_moving_or_retiring_a_unit_a_build_holds_is_a_conflict(
    client: TestClient, world: World, held: UnitStatus
) -> None:
    # Requirement 3.8: refused with 409, saying what frees the unit.
    reserved = 1 if held is UnitStatus.RESERVED else 0
    lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=reserved, reserved=reserved)
    unit = world.hold_unit(UNIT_TRACKED_PART, lot, status=held)

    retire = client.post(f"{INVENTORY}/units/{unit.id}/retire", json={})
    move = client.post(
        f"{INVENTORY}/units/{unit.id}/move", json={"to_location_id": str(world.lab.id)}
    )

    assert retire.status_code == 409
    assert move.status_code == 409
    freed_by = "cancel the reservation" if held is UnitStatus.RESERVED else "dismantle the build"
    assert freed_by in retire.json()["detail"]


def test_a_reserved_unit_answers_its_revision_and_its_location(
    client: TestClient, world: World
) -> None:
    # Requirement 3.10: a reserved unit is still in its drawer, and names its revision.
    lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=1, reserved=1)
    unit = world.hold_unit(UNIT_TRACKED_PART, lot, status=UnitStatus.RESERVED)

    response = client.get(f"{INVENTORY}/units/{unit.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "reserved"
    assert body["revision_id"] == str(unit.revision_id)
    assert body["location"]["id"] == str(world.drawer.id)


def test_a_unit_in_use_answers_its_revision_and_no_location(
    client: TestClient, world: World
) -> None:
    # Requirement 3.10: a unit in use sits on a board, so it answers no location (decision 5).
    lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=0)
    unit = world.hold_unit(UNIT_TRACKED_PART, lot, status=UnitStatus.IN_USE)

    response = client.get(f"{INVENTORY}/units/{unit.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "in_use"
    assert body["revision_id"] == str(unit.revision_id)
    assert body["location"] is None


# --- Actions ------------------------------------------------------------------------------


def test_relabelling_sets_the_serial_and_mac(client: TestClient, world: World) -> None:
    # Requirement 5.6: a relabel stores the change and answers the unit.
    lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=1)
    unit = world.hold_unit(UNIT_TRACKED_PART, lot)

    response = client.patch(
        f"{INVENTORY}/units/{unit.id}", json={"serial": "SN-99", "mac": "aabb.ccdd.eeff"}
    )

    assert response.status_code == 200
    assert response.json()["serial"] == "SN-99"
    assert response.json()["mac"] == "aa:bb:cc:dd:ee:ff"


def test_relabelling_to_a_duplicate_serial_is_a_conflict(client: TestClient, world: World) -> None:
    # Requirement 5.1: two units of a part can't share a serial, ignoring case.
    lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=2)
    world.hold_unit(UNIT_TRACKED_PART, lot, serial=Serial("SN-TAKEN"))
    other = world.hold_unit(UNIT_TRACKED_PART, lot)

    response = client.patch(f"{INVENTORY}/units/{other.id}", json={"serial": "sn-taken"})

    assert response.status_code == 409


def test_moving_a_unit_repoints_it_to_the_destination(client: TestClient, world: World) -> None:
    # Requirement 4.1: a move repoints the unit to the destination lot.
    other = world.add_location("Bin 1", world.lab)
    lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=1)
    unit = world.hold_unit(UNIT_TRACKED_PART, lot)

    response = client.post(
        f"{INVENTORY}/units/{unit.id}/move", json={"to_location_id": str(other.id)}
    )

    assert response.status_code == 200
    assert response.json()["location"]["id"] == str(other.id)


def test_moving_a_unit_to_its_own_location_is_refused(client: TestClient, world: World) -> None:
    # Requirement 4.4: source and destination must differ, a 422.
    lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=1)
    unit = world.hold_unit(UNIT_TRACKED_PART, lot)

    response = client.post(
        f"{INVENTORY}/units/{unit.id}/move", json={"to_location_id": str(world.drawer.id)}
    )

    assert response.status_code == 422


def test_moving_a_retired_unit_is_refused(client: TestClient, world: World) -> None:
    # Requirement 4.5: a retired unit can't move, a 422.
    other = world.add_location("Bin 2", world.lab)
    lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=0)
    unit = world.hold_unit(UNIT_TRACKED_PART, lot, status=UnitStatus.RETIRED)

    response = client.post(
        f"{INVENTORY}/units/{unit.id}/move", json={"to_location_id": str(other.id)}
    )

    assert response.status_code == 422


def test_retiring_a_unit_flips_its_status_and_drops_the_balance(
    client: TestClient, world: World
) -> None:
    # Requirement 3.1: retire sets `retired` and writes the compensating ADJUST -1.
    lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=1)
    unit = world.hold_unit(UNIT_TRACKED_PART, lot)

    response = client.post(f"{INVENTORY}/units/{unit.id}/retire", json={"reason": "lost"})

    assert response.status_code == 200
    assert response.json()["status"] == "retired"
    assert int(world.inventory.balances.saved[lot.id].on_hand) == 0


def test_retire_defaults_its_reason_to_damaged(client: TestClient, world: World) -> None:
    # A body may omit the reason; `damaged` is the default (design's HTTP API).
    lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=1)
    unit = world.hold_unit(UNIT_TRACKED_PART, lot)

    response = client.post(f"{INVENTORY}/units/{unit.id}/retire", json={})

    assert response.status_code == 200
    adjust = world.inventory.ledger.saved[-1]
    assert adjust.reason is MovementReason.DAMAGED


def test_unretiring_a_unit_flips_it_back(client: TestClient, world: World) -> None:
    # Requirement 3.2: un-retire sets `in_stock` and writes the compensating ADJUST +1.
    lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=0)
    unit = world.hold_unit(UNIT_TRACKED_PART, lot, status=UnitStatus.RETIRED)

    response = client.post(f"{INVENTORY}/units/{unit.id}/unretire")

    assert response.status_code == 200
    assert response.json()["status"] == "in_stock"
    assert int(world.inventory.balances.saved[lot.id].on_hand) == 1


def test_deleting_a_retired_unit_answers_no_content(client: TestClient, world: World) -> None:
    # Requirement 6.4: a retired unit may be deleted.
    lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=0)
    unit = world.hold_unit(UNIT_TRACKED_PART, lot, status=UnitStatus.RETIRED)

    response = client.delete(f"{INVENTORY}/units/{unit.id}")

    assert response.status_code == 204
    # To the trash (16's requirement 1.1): absent from the API from then on.
    assert world.inventory.units.saved[unit.id].in_trash
    assert client.get(f"{INVENTORY}/units/{unit.id}").status_code == 404


def test_deleting_an_in_stock_unit_is_a_conflict(client: TestClient, world: World) -> None:
    # Requirement 6.4: an in-stock unit can't be deleted, a 409.
    lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=1)
    unit = world.hold_unit(UNIT_TRACKED_PART, lot)

    response = client.delete(f"{INVENTORY}/units/{unit.id}")

    assert response.status_code == 409


# --- Wire contract ------------------------------------------------------------------------


def test_the_status_and_retire_reason_names_track_the_domain() -> None:
    # A new status or a new retire reason stops here until the wire union lists it too, the
    # way files' `test_every_kind_has_a_validator` keeps its own contract honest.
    assert set(get_args(UnitStatusName.__value__)) == {s.value for s in UnitStatus}
    assert set(get_args(RetireReasonName.__value__)) == {
        MovementReason.DAMAGED.value,
        MovementReason.LOST.value,
    }
