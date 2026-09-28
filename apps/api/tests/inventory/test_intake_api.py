"""The intake routes over the in-memory fakes: a bare FastAPI, no database.

Quick-add, a sheet's preview and import, and the template. The workspace dependency is a stub,
because resolving it is identity's job and the composition root's wiring; the session and
CSRF checks are `test_inventory_auth.py`'s. What is asserted here is the router's own
contract: each route's status, the bodies on the wire, and the structured refusals the web
reads a field, a row or a part out of (design's HTTP API and Error Handling).

The bench is the fakes' *Lab → Drawer 3* (`WX-L-0001`, `WX-L-0002`), with a lot-counted
*Passives / Resistors* and a unit-tracked *Boards*.
"""

from typing import Any, get_args

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from support.inventory import BENCH, World
from wiredex.inventory.api.router import create_router
from wiredex.inventory.api.schemas import ProblemCodeName, SheetRefusalName
from wiredex.inventory.domain.intake import ProblemCode
from wiredex.inventory.domain.sheet import MAX_SHEET_CHARACTERS, SheetRefusal
from wiredex.inventory.domain.values import WorkspaceId

INVENTORY = "/api/inventory"
MADE_UP = "0199aaaa-0000-7000-8000-000000000000"
HEADER = "category,name,manufacturer,mpn,location,quantity,serial,mac"


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


def sheet_of(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def answered(response: Any, status: int) -> dict[str, Any]:
    """The body of a response expected to have `status`, so a test can get on with its point."""
    assert response.status_code == status, response.text
    body: dict[str, Any] = response.json()
    return body


def where(problems: list[dict[str, Any]]) -> list[tuple[Any, Any, Any]]:
    return [(problem["row"], problem["column"], problem["code"]) for problem in problems]


def preview(client: TestClient, text: str) -> dict[str, Any]:
    return answered(client.post(f"{INVENTORY}/imports/preview", json={"csv": text}), 200)


# --- Quick-add -----------------------------------------------------------------------------


def test_a_quick_add_with_a_lot_answers_the_part_and_its_balance(
    client: TestClient, world: World
) -> None:
    body = answered(
        client.post(
            f"{INVENTORY}/quick-add",
            json={
                "part": {"category_id": str(world.resistors.id), "name": "10k 0805"},
                "stock": {"location_id": str(world.drawer.id), "quantity": 25},
            },
        ),
        201,
    )

    # Requirement 1.2: one RECEIVE, answered with the lot's balance so the web needs no refetch.
    assert body["name"] == "10k 0805"
    assert body["part_id"] == str(next(iter(world.inventory.catalog.parts)))
    assert body["balance"]["on_hand"] == 25
    assert body["balance"]["available"] == 25
    assert body["units"] == []
    assert world.inventory.commits == 1


def test_a_quick_added_board_answers_its_units_with_codes_and_location(
    client: TestClient, world: World
) -> None:
    body = answered(
        client.post(
            f"{INVENTORY}/quick-add",
            json={
                "part": {"category_id": str(world.boards.id), "name": "ESP32-C3 SuperMini"},
                "stock": {"location_id": str(world.drawer.id), "quantity": 3},
            },
        ),
        201,
    )

    # Requirement 1.3: that many units, blank labels, each with its code and where it sits.
    assert body["balance"] is None
    assert [unit["code"] for unit in body["units"]] == ["WX-U-0001", "WX-U-0002", "WX-U-0003"]
    assert {unit["location"]["code"] for unit in body["units"]} == {"WX-L-0002"}
    assert {(unit["serial"], unit["mac"]) for unit in body["units"]} == {(None, None)}


def test_a_part_alone_answers_no_balance_and_no_units(client: TestClient, world: World) -> None:
    body = answered(
        client.post(
            f"{INVENTORY}/quick-add",
            json={"part": {"category_id": str(world.resistors.id), "name": "4k7 0805"}},
        ),
        201,
    )

    assert (body["name"], body["balance"], body["units"]) == ("4k7 0805", None, [])


def test_null_and_blank_attributes_are_not_given_and_the_rest_reach_the_catalog(
    client: TestClient, world: World
) -> None:
    sensors = world.inventory.catalog.add_category("Sensors", required=["i2c_address"])

    refused = client.post(
        f"{INVENTORY}/quick-add",
        json={
            "part": {
                "category_id": str(sensors.id),
                "name": "BME280 breakout",
                "attributes": {"i2c_address": "  ", "notes": None, "smd": True, "rail": "3V3"},
            }
        },
    )
    body = answered(refused, 422)

    # A required value left blank is missing, not a refused value; null is nothing sent.
    assert where(body["detail"]["problems"]) == [(None, "i2c_address", "missing")]
    answered(
        client.post(
            f"{INVENTORY}/quick-add",
            json={
                "part": {
                    "category_id": str(sensors.id),
                    "name": "BME280 breakout",
                    "attributes": {"i2c_address": "0x76", "smd": False, "notes": None},
                }
            },
        ),
        201,
    )
    assert world.inventory.catalog.defined[0].attributes == {"i2c_address": "0x76", "smd": False}


def test_every_problem_of_a_quick_add_comes_back_at_once_on_its_field(
    client: TestClient, world: World
) -> None:
    response = client.post(
        f"{INVENTORY}/quick-add",
        json={
            "part": {"category_id": MADE_UP},
            "stock": {"location_id": MADE_UP, "quantity": 0},
        },
    )

    # Requirements 1.5, 1.8, 1.9: one 422, each problem naming its field, with a code the web
    # translates and a sentence it shows as the detail; a quick-add has no row.
    detail = answered(response, 422)["detail"]
    assert detail["message"] == "the part can't be added as it is"
    assert where(detail["problems"]) == [
        (None, "category", "unknown_category"),
        (None, "name", "missing"),
        (None, "location", "unknown_location"),
        (None, "quantity", "bad_quantity"),
    ]
    assert all(problem["message"] for problem in detail["problems"])
    # Requirement 1.4: nothing written.
    assert world.inventory.catalog.defined == []
    assert world.inventory.commits == 0


def test_a_quick_add_whose_part_number_is_held_names_the_part(
    client: TestClient, world: World
) -> None:
    held = world.inventory.catalog.hold_part(
        "10k 0805", world.resistors, manufacturer="Yageo", mpn="RC0805FR-0710KL"
    )

    response = client.post(
        f"{INVENTORY}/quick-add",
        json={
            "part": {
                "category_id": str(world.resistors.id),
                "name": "Another 10k",
                "manufacturer": "Yageo",
                "mpn": "RC0805FR-0710KL",
            }
        },
    )

    # Requirement 1.6: a 409 carrying the part, so the dialog can link to it.
    assert answered(response, 409)["detail"] == {
        "message": "RC0805FR-0710KL is already the part 10k 0805",
        "part_id": str(held.id),
        "name": "10k 0805",
    }
    assert world.inventory.commits == 0


def test_a_duplicate_of_a_part_the_workspace_doesnt_hold_is_not_found(
    client: TestClient, world: World
) -> None:
    response = client.post(
        f"{INVENTORY}/quick-add",
        json={
            "part": {"category_id": str(world.resistors.id), "name": "10k 0805, copy"},
            "pinout_from": MADE_UP,
        },
    )

    # Requirement 3.4: 404, and nothing defined.
    assert response.status_code == 404
    assert world.inventory.catalog.defined == []


@pytest.mark.parametrize(
    ("stock", "missing"),
    [({"quantity": 5}, "location_id"), ({"location_id": MADE_UP}, "quantity")],
)
def test_a_stock_pair_missing_a_half_is_refused(
    client: TestClient, world: World, stock: dict[str, Any], missing: str
) -> None:
    response = client.post(
        f"{INVENTORY}/quick-add",
        json={"part": {"category_id": str(world.resistors.id), "name": "10k"}, "stock": stock},
    )

    # Requirement 1.7: refused by the request schema, naming the half it lacks.
    errors = answered(response, 422)["detail"]
    assert [error["loc"] for error in errors] == [["body", "stock", missing]]
    assert world.inventory.commits == 0


# --- Preview -------------------------------------------------------------------------------


def test_a_preview_answers_every_row_the_summary_and_the_digest(
    client: TestClient, world: World
) -> None:
    held = world.inventory.catalog.hold_part(
        "4k7 0805", world.resistors, manufacturer="Yageo", mpn="RC0805FR-074K7L"
    )
    text = sheet_of(
        HEADER,
        "Passives / Resistors, 10k   0805 ,Yageo,RC0805FR-0710KL,WX-L-0002,200,,",
        ",,Yageo,RC0805FR-0710KL,Lab,50,,",
        ",,Yageo,rc0805fr-074k7l,wx-l-0002,25,,",
        "Boards,ESP32 board,,,Drawer 3,,SN-1,AA-BB-CC-DD-EE-FF",
        "Boards,Pico,,,,,,",
    )

    body = preview(client, text)

    # Requirement 7.4: the digest the import sends back, the plan's own.
    assert len(body["digest"]) == 64
    assert body["problems"] == []
    assert body["summary"] == {
        "rows": 5,
        "new_parts": 3,
        "existing_parts": 1,
        "receipts": 3,
        "pieces": 275,
        "units": 1,
        "rows_with_problems": 0,
    }
    rows = body["rows"]
    assert [row["row"] for row in rows] == [2, 3, 4, 5, 6]
    # Requirement 7.2: the part each row defines or names, and the stock it puts away.
    assert [row["part"] for row in rows] == [
        {
            "kind": "new",
            "part_id": None,
            "name": "10k 0805",
            "category": "Passives / Resistors",
            "same_as_row": None,
        },
        {
            "kind": "same_as_row",
            "part_id": None,
            "name": "10k 0805",
            "category": "Passives / Resistors",
            "same_as_row": 2,
        },
        {
            "kind": "existing",
            "part_id": str(held.id),
            "name": "4k7 0805",
            "category": None,
            "same_as_row": None,
        },
        {
            "kind": "new",
            "part_id": None,
            "name": "ESP32 board",
            "category": "Boards",
            "same_as_row": None,
        },
        {"kind": "new", "part_id": None, "name": "Pico", "category": "Boards", "same_as_row": None},
    ]
    stocks = [row["stock"] for row in rows]
    assert [(s["kind"], s["location"]["code"], s["quantity"]) for s in stocks[:4]] == [
        ("lot", "WX-L-0002", 200),
        ("lot", "WX-L-0001", 50),
        ("lot", "WX-L-0002", 25),
        ("units", "WX-L-0002", 1),
    ]
    assert stocks[0]["units"] == []
    # The MAC in its canonical form, as the import will store it (requirement 6.10).
    assert stocks[3]["units"] == [{"serial": "SN-1", "mac": "aa:bb:cc:dd:ee:ff"}]
    assert stocks[4] is None
    # A preview only reads (requirement 7.1).
    assert world.inventory.commits == 0
    assert world.inventory.catalog.defined == []


def test_a_preview_with_problems_still_answers_200_with_them_on_their_rows(
    client: TestClient, world: World
) -> None:
    text = sheet_of(
        HEADER,
        "Passives / Resistors,10k 0805,,,Nowhere,200,,",
        ",Pico,,,WX-L-0002,,,",
        "Boards,ESP32 board,,,WX-L-0002,,,not-a-mac",
    )

    body = preview(client, text)

    # Requirement 7.5: finding problems is what a preview is for, so it is a 200.
    assert [where(row["problems"]) for row in body["rows"]] == [
        [(2, "location", "unknown_location")],
        [(3, "category", "missing"), (3, "quantity", "quantity_needed")],
        [(4, "mac", "bad_mac")],
    ]
    assert body["summary"]["rows_with_problems"] == 3
    assert [row["stock"] for row in body["rows"]] == [None, None, None]
    assert world.inventory.commits == 0


def test_a_sheets_own_problem_is_answered_above_its_rows(client: TestClient) -> None:
    text = sheet_of(HEADER, *(f"Boards,Board {n},,,WX-L-0002,100,," for n in range(6)))

    body = preview(client, text)

    # Requirement 6.11: 600 units is the sheet's problem, with no row and no column.
    assert where(body["problems"]) == [(None, None, "sheet_too_many_units")]
    assert all(row["problems"] == [] for row in body["rows"])


@pytest.mark.parametrize(
    ("text", "code", "column"),
    [
        ("", "empty", None),
        ("name;colour?\n", "unknown_column", "colour?"),
        ("name,quantity,quantidade\n", "duplicate_column", "quantity"),
        ("name,qty\nR\ufffd,1\n", "not_utf8", None),
    ],
)
def test_a_sheet_that_cant_be_read_is_refused_with_its_code_and_column(
    client: TestClient, text: str, code: str, column: str | None
) -> None:
    response = client.post(f"{INVENTORY}/imports/preview", json={"csv": text})

    # Requirement 4.6: a 422 saying which, by a code the web translates.
    detail = answered(response, 422)["detail"]
    assert (detail["code"], detail["column"]) == (code, column)
    assert detail["message"]


def test_a_sheet_longer_than_its_cap_is_refused_by_the_request_schema(client: TestClient) -> None:
    text = "name\n" + "x" * (MAX_SHEET_CHARACTERS - 5)
    assert len(text) == MAX_SHEET_CHARACTERS
    response = client.post(f"{INVENTORY}/imports/preview", json={"csv": text + "y"})

    errors = answered(response, 422)["detail"]
    assert [error["loc"] for error in errors] == [["body", "csv"]]


# --- Import --------------------------------------------------------------------------------


def test_an_import_with_its_previews_digest_answers_what_it_did(
    client: TestClient, world: World
) -> None:
    text = sheet_of(
        HEADER,
        "Passives / Resistors,10k 0805,Yageo,RC0805FR-0710KL,WX-L-0002,200,,",
        "Boards,ESP32 board,,,WX-L-0002,,SN-1,",
        ",,Yageo,RC0805FR-0710KL,WX-L-0002,50,,",
    )
    digest = preview(client, text)["digest"]

    body = answered(client.post(f"{INVENTORY}/imports", json={"csv": text, "digest": digest}), 201)

    # Requirement 8.5: the summary, the parts defined with their rows, and the units received
    # with their codes and locations.
    assert body["summary"]["new_parts"] == 2
    assert body["summary"]["pieces"] == 250
    assert [(part["row"], part["name"]) for part in body["parts"]] == [
        (2, "10k 0805"),
        (3, "ESP32 board"),
    ]
    assert {part["part_id"] for part in body["parts"]} == {
        str(part_id) for part_id in world.inventory.catalog.parts
    }
    [unit] = body["units"]
    assert (unit["code"], unit["serial"], unit["location"]["code"]) == (
        "WX-U-0001",
        "SN-1",
        "WX-L-0002",
    )
    assert world.inventory.commits == 1


def test_an_import_whose_plan_has_problems_is_refused_with_them(
    client: TestClient, world: World
) -> None:
    text = sheet_of(HEADER, "Passives / Resistors,10k 0805,,,Nowhere,200,,")
    digest = preview(client, text)["digest"]

    response = client.post(f"{INVENTORY}/imports", json={"csv": text, "digest": digest})

    # Requirement 8.2: a 422 with the problems, the same structure a quick-add's has.
    detail = answered(response, 422)["detail"]
    assert detail["message"] == "the sheet can't be imported as it is"
    assert where(detail["problems"]) == [(2, "location", "unknown_location")]
    assert world.inventory.commits == 0


def test_an_import_whose_outcome_changed_since_its_preview_is_a_conflict(
    client: TestClient, world: World
) -> None:
    text = sheet_of(HEADER, "Passives / Resistors,10k 0805,Yageo,RC0805FR-0710KL,,,,")
    digest = preview(client, text)["digest"]
    # Meanwhile the part number appears: the row now names that part instead of defining it.
    world.inventory.catalog.hold_part(
        "10k 0805", world.resistors, manufacturer="Yageo", mpn="RC0805FR-0710KL"
    )

    response = client.post(f"{INVENTORY}/imports", json={"csv": text, "digest": digest})

    # Requirement 8.3: 409, saying so, and nothing written.
    assert answered(response, 409)["detail"] == (
        "the sheet's outcome changed since its preview; preview it again"
    )
    assert world.inventory.commits == 0


@pytest.mark.parametrize("digest", ["", "abc", "A" * 64, "g" * 64, "a" * 65])
def test_a_digest_that_isnt_64_lower_case_hex_is_refused_by_the_request_schema(
    client: TestClient, digest: str
) -> None:
    response = client.post(f"{INVENTORY}/imports", json={"csv": "name\nR\n", "digest": digest})

    errors = answered(response, 422)["detail"]
    assert [error["loc"] for error in errors] == [["body", "digest"]]


# --- Template ------------------------------------------------------------------------------


def test_the_template_is_a_csv_download_of_the_fixed_columns(client: TestClient) -> None:
    response = client.get(f"{INVENTORY}/imports/template")

    # Requirement 4.9: the header row of the nine fixed columns, and nothing else.
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"] == 'attachment; filename="wiredex-import.csv"'
    fixed = "category,name,manufacturer,mpn,package,location,quantity,serial,mac"
    assert response.text == f"{fixed}\r\n"


# --- The wire's names ----------------------------------------------------------------------


def test_the_wire_names_every_problem_code_and_sheet_refusal() -> None:
    # A new code stops here until the client's union lists it too, and with it a sentence
    # in both locale files, the way `MovementReasonName` keeps its own contract honest.
    assert set(get_args(ProblemCodeName.__value__)) == {code.value for code in ProblemCode}
    assert set(get_args(SheetRefusalName.__value__)) == {code.value for code in SheetRefusal}
