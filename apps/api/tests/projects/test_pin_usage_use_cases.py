"""A part's pin usage over the in-memory fakes (12-wiring-validation, requirement 7).

The board sits on U1 of *Weather station* `A` and `B` and on U3 of *Greenhouse* `A`; the
sensor on U2 shares the nets, so each read has another part's references to leave out.
"""

from decimal import Decimal
from uuid import uuid7

import pytest

from support.bom import a_line
from support.netlist import a_net, content_of
from support.projects import World
from wiredex.projects.domain.errors import PartNotFoundError
from wiredex.projects.domain.pins import PartPins, PinFacts, PinNumber, PinType
from wiredex.projects.domain.revision import Revision
from wiredex.projects.domain.values import PartId, RevisionStatus

pytestmark = pytest.mark.anyio


class Bench:
    def __init__(self) -> None:
        self.world = World()
        parts = self.world.work.parts
        self.board = parts.hold("ESP32-DevKitC")
        self.sensor = parts.hold("BME280")
        self.world.work.pins.pinouts[self.board] = PartPins(
            tuple(
                PinFacts(PinNumber(number), label, PinType.IO, (), Decimal(3))
                for number, label in (("25", "GPIO21"), ("14", "GND"), ("22", "GPIO22"))
            )
        )
        weather = self.world.hold_project("Weather station", revision=None)
        greenhouse = self.world.hold_project("greenhouse", revision=None)
        self.weather_a = self.world.hold_revision(weather, "A", status=RevisionStatus.BUILT)
        self.weather_b = self.world.hold_revision(weather, "B", minutes=5)
        self.greenhouse = self.world.hold_revision(greenhouse, "A", minutes=10)
        for revision, board_on in ((self.weather_a, "U1"), (self.weather_b, "U1")):
            self.line(revision, self.board, board_on)
            self.line(revision, self.sensor, "U2")
        self.line(self.greenhouse, self.board, "U1, U3")

    def line(self, revision: Revision, part_id: PartId, designators: str) -> None:
        line = a_line(revision, part_id, designators)
        self.world.work.bom_lines.saved[line.id] = line

    def net(self, revision: Revision, name: str, *pins: str) -> None:
        net = a_net(revision, content_of(name, *pins))
        self.world.work.nets.saved[net.id] = net


async def test_uses_come_by_project_then_revision_then_designator_whatever_the_status() -> None:
    bench = Bench()
    bench.net(bench.weather_b, "SDA", "U1.25", "U2.3")
    bench.net(bench.weather_a, "SDA", "U1.25", "U2.3")
    bench.net(bench.greenhouse, "SDA", "U3.25", "U1.25")

    usage = await bench.world.get_pin_usage(bench.greenhouse.workspace_id, bench.board)

    (gpio21, gnd, gpio22), others = usage.pins, usage.others
    assert [
        (str(use.project_name), str(use.revision_label), str(use.designator), use.status)
        for use in gpio21[1]
    ] == [
        ("greenhouse", "A", "U1", RevisionStatus.DRAFT),
        ("greenhouse", "A", "U3", RevisionStatus.DRAFT),
        ("Weather station", "A", "U1", RevisionStatus.BUILT),
        ("Weather station", "B", "U1", RevisionStatus.DRAFT),
    ]
    assert (gnd[1], gpio22[1], others) == ((), (), ())
    assert usage.part.name == "ESP32-DevKitC"


async def test_a_number_the_pinout_lacks_is_another_pin() -> None:
    bench = Bench()
    bench.net(bench.weather_b, "SOIL", "U1.34")

    usage = await bench.world.get_pin_usage(bench.weather_b.workspace_id, bench.board)

    assert [
        (str(number), [str(use.net_name) for use in uses]) for number, uses in usage.others
    ] == [("34", ["SOIL"])]


async def test_a_part_without_a_pinout_answers_its_uses_as_other_pins() -> None:
    bench = Bench()
    bench.net(bench.weather_a, "SDA", "U1.25", "U2.3")

    usage = await bench.world.get_pin_usage(bench.weather_a.workspace_id, bench.sensor)

    assert not usage.has_pinout
    assert [str(number) for number, _ in usage.others] == ["3"]


async def test_a_part_the_bench_doesnt_hold_is_not_found() -> None:
    bench = Bench()

    with pytest.raises(PartNotFoundError):
        await bench.world.get_pin_usage(bench.weather_a.workspace_id, PartId(uuid7()))

    assert bench.world.work.nets.reads == 0
