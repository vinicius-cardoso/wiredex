"""The bench the wiring tests run on: the sample weather station in miniature, an ESP32 with a
pinout on U1, a BME280 with one on U2, and a resistor without one on R1 and R2, so every
resolution has a reference. Shared by the netlist's use-case tests and the paste's."""

from datetime import timedelta
from decimal import Decimal

from support.bom import a_line
from support.projects import World
from wiredex.projects.domain.netlist import NetDraft
from wiredex.projects.domain.pins import PartPins, PinFacts, PinNumber, PinType
from wiredex.projects.domain.values import NetId, RevisionStatus


def _pins(*rows: tuple[str, str, str]) -> PartPins:
    return PartPins(
        tuple(
            PinFacts(PinNumber(number), label, PinType.IO, tuple(functions.split()), Decimal(3))
            for number, label, functions in rows
        )
    )


class Bench:
    def __init__(self, status: RevisionStatus = RevisionStatus.DRAFT) -> None:
        self.world = World()
        project = self.world.hold_project("Weather station", revision=None)
        self.revision = self.world.hold_revision(project, "A", status=status)
        parts = self.world.work.parts
        self.esp32 = parts.hold("ESP32-DevKitC")
        self.bme280 = parts.hold("BME280")
        self.resistor = parts.hold("Resistor 4k7 0805")
        pins = self.world.work.pins.pinouts
        pins[self.esp32] = _pins(
            ("14", "GND", ""), ("20", "GND", ""), ("22", "GPIO22", "SCL"), ("25", "GPIO21", "SDA")
        )
        pins[self.bme280] = _pins(("3", "SDI", "SDA"), ("4", "SCK", "SCL"))
        lines = self.world.work.bom_lines.saved
        for part_id, designators in (
            (self.esp32, "U1"),
            (self.bme280, "U2"),
            (self.resistor, "R1, R2"),
        ):
            line = a_line(self.revision, part_id, designators)
            lines[line.id] = line
        self.world.clock.advance(timedelta(hours=1))

    async def add(self, name: str, pins: str, color: str | None = None) -> NetId:
        written = await self.world.add_net(
            self.revision.workspace_id,
            self.revision.id,
            NetDraft.parse(name, color, None, pins),
        )
        return written.net.id

    def remove_line(self, designators: str) -> None:
        lines = self.world.work.bom_lines.saved
        for line in list(lines.values()):
            if line.content.designators.text() == designators:
                del lines[line.id]
