"""The pin usage route over the in-memory fakes: a bare FastAPI, no database
(12-wiring-validation, HTTP). The board is on U1 of a weather station, with GPIO21 on SDA and
a pin 34 its pinout lacks on SOIL; the resistor on R1 has no pinout."""

from decimal import Decimal
from uuid import uuid7

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from support.bom import a_line
from support.netlist import a_net, content_of
from support.projects import BENCH, World
from wiredex.projects.api.router import create_router
from wiredex.projects.domain.netlist import WireColor
from wiredex.projects.domain.pins import PartPins, PinFacts, PinNumber, PinType
from wiredex.projects.domain.values import RevisionStatus, WorkspaceId


async def the_bench(_request: Request) -> WorkspaceId:
    return BENCH


class Bench:
    def __init__(self) -> None:
        self.world = World()
        project = self.world.hold_project("Weather station", revision=None)
        self.revision = self.world.hold_revision(project, "A", status=RevisionStatus.BUILT)
        self.esp32 = self.world.work.parts.hold("ESP32-DevKitC")
        self.resistor = self.world.work.parts.hold("Resistor 4k7 0805")
        self.world.work.pins.pinouts[self.esp32] = PartPins(
            (
                PinFacts(PinNumber("14"), "GND", PinType.GROUND),
                PinFacts(PinNumber("25"), "GPIO21", PinType.IO, ("SDA",), Decimal("3.3")),
            )
        )
        for part_id, designators in ((self.esp32, "U1"), (self.resistor, "R1")):
            line = a_line(self.revision, part_id, designators)
            self.world.work.bom_lines.saved[line.id] = line
        for content in (
            content_of("SDA", "U1.25", "R1.2", color=WireColor.BLUE),
            content_of("SOIL", "U1.34", "R1.1"),
        ):
            net = a_net(self.revision, content)
            self.world.work.nets.saved[net.id] = net
        app = FastAPI()
        app.include_router(create_router(self.world.projects_use_cases(), the_bench), prefix="/api")
        self.client = TestClient(app)


@pytest.fixture
def bench() -> Bench:
    return Bench()


def test_a_parts_pins_come_with_their_nets_and_free_pins_empty(bench: Bench) -> None:
    response = bench.client.get(f"/api/projects/parts/{bench.esp32}/pin-usage")

    assert response.status_code == 200
    body = response.json()
    assert (body["part_name"], body["has_pinout"]) == ("ESP32-DevKitC", True)
    gnd, gpio21 = body["pins"]
    assert (gnd["number"], gnd["uses"]) == ("14", [])
    (use,) = gpio21["uses"]
    assert gpio21["label"] == "GPIO21"
    assert gpio21["voltage"] == "3.3"
    assert use == {
        "project_id": str(bench.revision.project_id),
        "project_name": "Weather station",
        "revision_id": str(bench.revision.id),
        "revision_label": "A",
        "status": "built",
        "designator": "U1",
        "net_id": use["net_id"],
        "net_name": "SDA",
        "color": "blue",
    }
    assert [(other["pin"], other["uses"][0]["net_name"]) for other in body["others"]] == [
        ("34", "SOIL")
    ]


def test_a_part_without_a_pinout_answers_other_pins(bench: Bench) -> None:
    body = bench.client.get(f"/api/projects/parts/{bench.resistor}/pin-usage").json()

    assert (body["has_pinout"], body["pins"]) == (False, [])
    assert [other["pin"] for other in body["others"]] == ["1", "2"]


def test_a_part_the_bench_doesnt_hold_is_not_found(bench: Bench) -> None:
    response = bench.client.get(f"/api/projects/parts/{uuid7()}/pin-usage")

    assert response.status_code == 404
