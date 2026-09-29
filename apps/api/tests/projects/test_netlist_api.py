"""The netlist routes over the in-memory fakes: a bare FastAPI, no database.

The router's own contract (11-netlist-editor, HTTP): every route's status, each refusal's body
with its code, field and item, and the shapes the netlist editor builds on. The bench is the
weather station in miniature: an ESP32 with a pinout on U1, a resistor without one on R1.
"""

from datetime import timedelta
from decimal import Decimal
from typing import Any, get_args
from uuid import uuid7

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from support.bom import a_line
from support.projects import BENCH, World
from wiredex.projects.api.router import create_router
from wiredex.projects.api.schemas import (
    NetFieldName,
    NetRefusalCodeName,
    PinTypeName,
    ResolutionName,
    WireColorName,
)
from wiredex.projects.domain.errors import NetField, NetRefusal
from wiredex.projects.domain.netlist import ResolutionState, WireColor
from wiredex.projects.domain.pins import PartPins, PinFacts, PinNumber, PinType
from wiredex.projects.domain.values import RevisionStatus, WorkspaceId

MADE_UP = "0199aaaa-0000-7000-8000-000000000000"


async def the_bench(_request: Request) -> WorkspaceId:
    return BENCH


class Bench:
    def __init__(self) -> None:
        self.world = World()
        project = self.world.hold_project("Weather station", revision=None)
        self.revision = self.world.hold_revision(project, "A")
        self.esp32 = self.world.work.parts.hold("ESP32-DevKitC")
        self.resistor = self.world.work.parts.hold("Resistor 4k7 0805")
        self.world.work.pins.pinouts[self.esp32] = PartPins(
            (
                PinFacts(PinNumber("14"), "GND", PinType.GROUND),
                PinFacts(PinNumber("20"), "GND", PinType.GROUND),
                PinFacts(PinNumber("25"), "GPIO21", PinType.IO, ("SDA",), Decimal("3.3")),
            )
        )
        for part_id, designators in ((self.esp32, "U1"), (self.resistor, "R1")):
            line = a_line(self.revision, part_id, designators)
            self.world.work.bom_lines.saved[line.id] = line
        self.world.clock.advance(timedelta(hours=1))
        app = FastAPI()
        app.include_router(create_router(self.world.projects_use_cases(), the_bench), prefix="/api")
        self.client = TestClient(app)

    @property
    def netlist(self) -> str:
        return f"/api/projects/revisions/{self.revision.id}/netlist"

    @property
    def nets(self) -> str:
        return f"{self.netlist}/nets"

    def add(self, body: dict[str, Any]) -> dict[str, Any]:
        response = self.client.post(self.nets, json=body)
        assert response.status_code == 201, response.text
        added: dict[str, Any] = response.json()
        return added


@pytest.fixture
def bench() -> Bench:
    return Bench()


def refusal(response: Any) -> dict[str, Any]:
    detail: dict[str, Any] = response.json()["detail"]
    return detail


def test_a_net_is_added_and_answered_resolved(bench: Bench) -> None:
    added = bench.add({"name": " SDA ", "color": "blue", "pins": "u1.sda, R1.2"})

    assert (added["name"], added["color"], added["notes"]) == ("SDA", "blue", None)
    assert added["pins_text"] == "R1.2, U1.25"
    r1, u1 = added["pins"]
    assert (r1["resolution"], r1["part_name"], r1["label"]) == (
        "unchecked",
        "Resistor 4k7 0805",
        None,
    )
    assert (u1["ref"], u1["resolution"], u1["label"], u1["type"], u1["voltage"]) == (
        "U1.25",
        "resolved",
        "GPIO21",
        "io",
        "3.3",
    )


def test_the_netlist_answers_its_nets_summary_designators_and_parts(bench: Bench) -> None:
    bench.add({"name": "SDA", "pins": "U1.25, R1.2"})

    body = bench.client.get(bench.netlist).json()

    assert body["editable"] is True
    assert body["summary"] == {"nets": 1, "references": 2, "unchecked": 1, "unresolved": 0}
    assert [item["designator"] for item in body["designators"]] == ["R1", "U1"]
    parts = {part["name"]: part for part in body["parts"]}
    assert parts["Resistor 4k7 0805"]["has_pinout"] is False
    assert [pin["number"] for pin in parts["ESP32-DevKitC"]["pins"]] == ["14", "20", "25"]


@pytest.mark.parametrize(
    ("pins", "status", "code", "item"),
    [
        ("U9.1", 422, "unknown_designator", "U9.1"),
        ("U1.99", 422, "unknown_pin", "U1.99"),
        ("U1", 422, "invalid_pin_ref", "U1"),
        ("U1.25, U1.GPIO21", 422, "repeated_pin", "U1.GPIO21"),
        (" ", 422, "no_pins", None),
    ],
)
def test_a_refused_pin_names_its_code_field_and_item(
    bench: Bench, pins: str, status: int, code: str, item: str | None
) -> None:
    response = bench.client.post(bench.nets, json={"name": "N", "pins": pins})

    assert response.status_code == status
    detail = refusal(response)
    assert (detail["code"], detail["field"], detail["item"]) == (code, "pins", item)


def test_an_ambiguous_pin_names_its_candidates(bench: Bench) -> None:
    response = bench.client.post(bench.nets, json={"name": "GND", "pins": "U1.GND"})

    assert response.status_code == 422
    assert refusal(response)["candidates"] == ["14", "20"]


def test_a_taken_name_is_a_409_naming_the_net(bench: Bench) -> None:
    first = bench.add({"name": "SDA", "pins": "U1.25"})

    response = bench.client.post(bench.nets, json={"name": "sda", "pins": "R1.1"})

    assert response.status_code == 409
    detail = refusal(response)
    assert (detail["code"], detail["field"], detail["net_id"], detail["net"]) == (
        "net_name_taken",
        "name",
        first["id"],
        "SDA",
    )


def test_a_color_outside_the_ten_is_refused_on_the_color(bench: Bench) -> None:
    response = bench.client.post(bench.nets, json={"name": "N", "color": "pink", "pins": "R1.1"})

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "color"]


def test_a_locked_revision_refuses_writes_with_its_code(bench: Bench) -> None:
    added = bench.add({"name": "SDA", "pins": "U1.25"})
    bench.revision.status = RevisionStatus.RESERVED

    posted = bench.client.post(bench.nets, json={"name": "SCL", "pins": "R1.1"})
    deleted = bench.client.delete(f"{bench.nets}/{added['id']}")

    assert (posted.status_code, refusal(posted)["code"]) == (409, "revision_locked")
    assert (deleted.status_code, refusal(deleted)["code"]) == (409, "revision_locked")
    assert bench.client.get(bench.netlist).json()["editable"] is False


def test_an_edit_and_a_removal(bench: Bench) -> None:
    added = bench.add({"name": "SDA", "pins": "U1.25"})

    edited = bench.client.patch(
        f"{bench.nets}/{added['id']}", json={"name": "SDA", "color": "yellow", "pins": "U1.25"}
    )
    removed = bench.client.delete(f"{bench.nets}/{added['id']}")

    assert (edited.status_code, edited.json()["color"]) == (200, "yellow")
    assert removed.status_code == 204
    assert bench.client.get(bench.netlist).json()["nets"] == []


@pytest.mark.parametrize("method", ["PATCH", "DELETE"])
def test_an_unknown_net_or_revision_is_a_404(bench: Bench, method: str) -> None:
    body = {"name": "N", "pins": "R1.1"}

    net = bench.client.request(method, f"{bench.nets}/{MADE_UP}", json=body)
    revision = bench.client.get(f"/api/projects/revisions/{uuid7()}/netlist")

    assert (net.status_code, revision.status_code) == (404, 404)


def test_the_wire_names_follow_their_enums() -> None:
    assert set(get_args(WireColorName.__value__)) == {color.value for color in WireColor}
    assert set(get_args(ResolutionName.__value__)) == {state.value for state in ResolutionState}
    assert set(get_args(PinTypeName.__value__)) == {kind.value for kind in PinType}
    assert set(get_args(NetFieldName.__value__)) == {field.value for field in NetField}
    assert set(get_args(NetRefusalCodeName.__value__)) == {code.value for code in NetRefusal}
