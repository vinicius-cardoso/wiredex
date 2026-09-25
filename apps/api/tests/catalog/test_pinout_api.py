"""The two pinout routes over the in-memory fakes, as the other catalog routes are tested.

What is asserted here is the wire, not the rules: the shapes a pin travels in, and the one
refusal in the catalog that answers a structured detail instead of a sentence, because a
table of forty rows can't be fixed from a message alone (design's "Error Handling").

The bench is the fakes' *Passives → Resistors*, with the part the pins hang off written
straight to the store: which part it is makes no difference to any of these answers.
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from support.catalog import BENCH, World
from wiredex.catalog.api.router import create_router
from wiredex.catalog.domain.pinout import Pinout
from wiredex.catalog.domain.values import PartDefinitionId, WorkspaceId

CATALOG = "/api/catalog"
MADE_UP = PartDefinitionId(UUID("0199aaaa-0000-7000-8000-000000000000"))

# One row of a table as it goes over the wire: text in every cell, and cells left out.
type Row = dict[str, Any]

# Four of the BME280's eight pins, spelled as an owner types them: a ball in lower case, two
# levels written two ways, one pin carrying alternate functions, one with no level at all.
BME280: list[Row] = [
    {"number": "1", "label": "GND", "type": "ground"},
    {"number": "3", "label": "SDI", "type": "io", "functions": ["SDA", "MOSI"], "voltage": "3V3"},
    {"number": "a4", "label": "SCK", "type": "io", "functions": ["SCL"], "voltage": "3.3"},
    {"number": "8", "label": "VDD", "type": "power"},
]


async def the_bench(_request: Request) -> WorkspaceId:
    """What `bootstrap/app.py` builds from the session: the workspace this request acts in."""
    return BENCH


@pytest.fixture
def world() -> World:
    return World()


@pytest.fixture
def client(world: World) -> TestClient:
    app = FastAPI()
    app.include_router(create_router(world.catalog_use_cases(), the_bench), prefix="/api")
    return TestClient(app)


@pytest.fixture
def pinout(world: World) -> str:
    """The pinout route of a part that exists and has no pins yet."""
    return f"{CATALOG}/parts/{world.add_part(world.resistors, 'BME280').id}/pinout"


def saved(client: TestClient, pinout: str, pins: list[dict[str, Any]]) -> dict[str, Any]:
    """PUTs a table that is expected to be stored, so a test can get on with its point."""
    response = client.put(pinout, json={"pins": pins})
    assert response.status_code == 200, response.text
    stored: dict[str, Any] = response.json()
    return stored


def test_a_saved_table_comes_back_normalized_and_in_order(client: TestClient, pinout: str) -> None:
    # Requirements 1.1, 2.1, 2.13: the order typed, the ball upper-cased, and a level in both
    # the exact value and the form a bench prints it in.
    stored = saved(client, pinout, BME280)

    assert [pin["number"] for pin in stored["pins"]] == ["1", "3", "A4", "8"]
    assert stored["pins"][1] == {
        "number": "3",
        "label": "SDI",
        "type": "io",
        "functions": ["SDA", "MOSI"],
        "voltage": {"value": "3.3", "display": "3.3V"},
    }
    # 3V3 and 3.3 are one level, so both rows read the same way out.
    assert stored["pins"][2]["voltage"] == {"value": "3.3", "display": "3.3V"}
    # A pin with no level says so, rather than leaving the field out (requirement 2.11).
    assert stored["pins"][0]["voltage"] is None
    assert client.get(pinout).json() == stored


def test_a_part_with_no_pins_reads_as_an_empty_table(client: TestClient, pinout: str) -> None:
    # Requirement 1.2: most parts never get a pin table, and asking for one isn't an error.
    response = client.get(pinout)

    assert response.status_code == 200
    assert response.json() == {"pins": []}


def test_saving_no_pins_clears_the_table(client: TestClient, pinout: str) -> None:
    # Requirement 1.4: emptying it is how a table entered by mistake is taken back.
    saved(client, pinout, BME280)

    assert saved(client, pinout, []) == {"pins": []}
    assert client.get(pinout).json() == {"pins": []}


def test_a_body_with_no_pins_field_clears_the_table_too(client: TestClient, pinout: str) -> None:
    # `{}` and `{"pins": []}` are the same request: there is no third thing a pinout could be.
    saved(client, pinout, BME280)

    response = client.put(pinout, json={})

    assert response.status_code == 200
    assert response.json() == {"pins": []}


def test_a_part_says_how_many_pins_it_has(client: TestClient, world: World) -> None:
    # Requirement 1.8: the count travels with the part, so a page knows whether to offer a
    # table without asking for one.
    defined = client.post(
        f"{CATALOG}/parts",
        json={
            "category_id": str(world.resistors.id),
            "name": "BME280",
            "attributes": {"resistance": "4k7"},
        },
    )

    assert defined.status_code == 201, defined.text
    # A part just defined can't have pins yet, and 0 is exactly what it has.
    assert defined.json()["pin_count"] == 0

    part_id = defined.json()["id"]
    saved(client, f"{CATALOG}/parts/{part_id}/pinout", BME280)

    assert client.get(f"{CATALOG}/parts/{part_id}").json()["pin_count"] == 4
    # An edit leaves the table where it was, so the answer to a patch says so too.
    patched = client.patch(
        f"{CATALOG}/parts/{part_id}",
        json={"name": "BME280 rev B", "attributes": {"resistance": "4k7"}},
    )

    assert patched.json()["pin_count"] == 4


@dataclass(frozen=True, slots=True)
class Refusal:
    """What the answer to a bad row has to say: which row, which cell, and in what words."""

    row: int
    field: str
    says: str


@pytest.mark.parametrize(
    ("pins", "refusal"),
    [
        pytest.param(
            [{"number": "SD A", "label": "GND", "type": "ground"}],
            Refusal(1, "number", "is not a pin number"),
            id="a number with a space in it",
        ),
        pytest.param(
            [
                {"number": "1", "label": "GND", "type": "ground"},
                {"number": "2", "label": "VDD", "type": "power"},
                {"number": "1", "label": "GND", "type": "ground"},
            ],
            Refusal(3, "number", "already row 1"),
            id="a duplicate number, naming both rows",
        ),
        pytest.param(
            [{"number": "1", "label": "", "type": "ground"}],
            Refusal(1, "label", "between 1 and 40 characters"),
            id="an empty label",
        ),
        pytest.param(
            [{"number": "1", "label": "GND", "type": "GND"}],
            Refusal(1, "type", "is not a pin type"),
            id="a pasted spelling the web should have mapped",
        ),
        pytest.param(
            [{"number": "1", "label": "SDI", "type": "io", "functions": ["SD A"]}],
            Refusal(1, "functions", "no spaces"),
            id="a function with a space in it",
        ),
        pytest.param(
            [{"number": "1", "label": "VDD", "type": "power", "voltage": "3.3A"}],
            Refusal(1, "voltage", "is not a voltage"),
            id="a level in another unit",
        ),
    ],
)
def test_a_refused_row_is_answered_with_its_row_and_its_cell(
    client: TestClient,
    world: World,
    pinout: str,
    pins: list[dict[str, Any]],
    refusal: Refusal,
) -> None:
    # Requirements 3.1 and 3.2: the editor marks a cell, so the answer names one.
    response = client.put(pinout, json={"pins": pins})

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert (detail["row"], detail["field"]) == (refusal.row, refusal.field)
    assert refusal.says in detail["message"]
    # The message alone still says where to look, for anything that only shows text.
    assert detail["message"].startswith(f"row {refusal.row}: ")
    assert world.catalog.pinouts.saved == {}


def test_a_table_refused_as_a_whole_is_answered_without_a_row(
    client: TestClient, pinout: str
) -> None:
    # Requirement 3.3: too many pins is nothing to mark, so there is no cell to point at.
    too_many = [
        {"number": str(number), "label": "GND", "type": "ground"}
        for number in range(Pinout.MAX_PINS + 1)
    ]

    response = client.put(pinout, json={"pins": too_many})

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "message": f"a pinout has at most {Pinout.MAX_PINS} pins",
        "row": None,
        "field": None,
    }


def test_a_refused_table_leaves_the_stored_one_untouched(client: TestClient, pinout: str) -> None:
    # Requirement 1.3: whole or not at all, so four good rows and one bad one save nothing.
    saved(client, pinout, BME280)

    refused = client.put(
        pinout, json={"pins": [*BME280, {"number": "1", "label": "GND", "type": "ground"}]}
    )

    assert refused.status_code == 422
    assert refused.json()["detail"]["row"] == 5
    assert len(client.get(pinout).json()["pins"]) == 4


def test_every_other_catalog_refusal_keeps_its_plain_message(
    client: TestClient, world: World
) -> None:
    """The structured detail is the pinout's alone, and nothing else changed shape.

    The pinout mapping runs inside the generic one, so a refusal that isn't a table's still
    answers `{"detail": "<message>"}` — which is what the part form reads the field out of.
    """
    response = client.post(
        f"{CATALOG}/parts",
        json={"category_id": str(world.resistors.id), "name": "R 4k7", "attributes": {}},
    )

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)


@pytest.mark.parametrize("method", ["GET", "PUT"])
def test_the_pinout_of_a_part_this_bench_does_not_hold_is_simply_not_found(
    client: TestClient, method: str
) -> None:
    # Requirement 1.9: another workspace's part is 404, never 403, as everywhere else.
    response = client.request(method, f"{CATALOG}/parts/{MADE_UP}/pinout", json={"pins": BME280})

    assert response.status_code == 404
    assert response.json()["detail"] == "that part doesn't exist"


def test_both_routes_act_in_the_callers_workspace(
    client: TestClient, world: World, pinout: str
) -> None:
    # ADR 0007's first gate is the unit of work being opened for one bench, and a route that
    # forgot to pass the workspace on couldn't reach a use case at all.
    saved(client, pinout, BME280)
    client.get(pinout)

    assert set(world.catalog.opened_for) == {BENCH}
    assert world.catalog.opened_for != []
