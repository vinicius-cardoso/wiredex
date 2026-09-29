"""The netlist use cases over the in-memory fakes (11-netlist-editor).

The bench is the sample weather station in miniature: an ESP32 with a pinout on U1, a BME280
with one on U2, and a resistor without one on R1 and R2, so every resolution has a reference.
"""

from datetime import timedelta
from decimal import Decimal
from uuid import uuid7

import pytest

from support.bom import a_line
from support.projects import World
from wiredex.projects.application.ports import NewRevision
from wiredex.projects.domain.errors import (
    AmbiguousPinError,
    NetNameTakenError,
    NetNotFoundError,
    RevisionContentLockedError,
    RevisionNotFoundError,
    UnknownDesignatorError,
    UnknownPinError,
)
from wiredex.projects.domain.netlist import NetDraft, ResolutionState
from wiredex.projects.domain.pins import PartPins, PinFacts, PinNumber, PinType
from wiredex.projects.domain.values import LocationId, NetId, RevisionId, RevisionStatus
from wiredex.projects.domain.wiring import FindingCode, Severity

pytestmark = pytest.mark.anyio

LOCKED = [RevisionStatus.RESERVED, RevisionStatus.BUILT, RevisionStatus.DISMANTLED]


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


async def test_a_net_is_added_under_the_projects_lock_and_touches_the_revision() -> None:
    bench = Bench()

    written = await bench.world.add_net(
        bench.revision.workspace_id,
        bench.revision.id,
        NetDraft.parse("SDA", "blue", None, "U1.SDA, U2.SDA, R1.2"),
    )

    assert written.net.content.pins.text() == "R1.2, U1.25, U2.3"
    assert bench.world.work.projects.locks == [bench.revision.project_id]
    assert bench.world.work.commits == 1
    assert bench.revision.updated_at == bench.world.clock.now()
    summary = written.view.summary()
    assert (summary.nets, summary.references, summary.unchecked, summary.unresolved) == (1, 3, 1, 0)


@pytest.mark.parametrize(
    ("pins", "error"),
    [("U3.1", UnknownDesignatorError), ("U1.99", UnknownPinError), ("U1.GND", AmbiguousPinError)],
)
async def test_a_refused_reference_writes_nothing(pins: str, error: type[Exception]) -> None:
    bench = Bench()

    with pytest.raises(error):
        await bench.add("N", pins)

    assert bench.world.work.nets.saved == {}
    assert bench.world.work.commits == 0


async def test_a_taken_name_is_refused_ignoring_case() -> None:
    bench = Bench()
    await bench.add("SDA", "U1.25")

    with pytest.raises(NetNameTakenError):
        await bench.add("sda", "U2.3")

    assert len(bench.world.work.nets.saved) == 1


@pytest.mark.parametrize("status", LOCKED)
async def test_only_a_drafts_netlist_changes(status: RevisionStatus) -> None:
    bench = Bench(status)

    with pytest.raises(RevisionContentLockedError):
        await bench.add("SDA", "U1.25")

    assert bench.world.work.commits == 0


async def test_an_unknown_revision_is_not_found() -> None:
    bench = Bench()

    with pytest.raises(RevisionNotFoundError):
        await bench.world.get_netlist(bench.revision.workspace_id, RevisionId(uuid7()))


async def test_an_edit_keeps_references_a_bom_edit_broke() -> None:
    bench = Bench()
    net_id = await bench.add("SDA", "U1.25, R1.2")
    bench.remove_line("R1, R2")

    written = await bench.world.update_net(
        bench.revision.workspace_id,
        bench.revision.id,
        net_id,
        NetDraft.parse("SDA", "yellow", None, "U1.25, R1.2"),
    )

    assert written.net.content.pins.text() == "R1.2, U1.25"
    view = await bench.world.get_netlist(bench.revision.workspace_id, bench.revision.id)
    states = {
        str(reference): view.resolution(reference).state
        for reference in view.netlist.nets[0].content.pins
    }
    assert states == {
        "R1.2": ResolutionState.UNKNOWN_DESIGNATOR,
        "U1.25": ResolutionState.RESOLVED,
    }
    assert view.summary().unresolved == 1


async def test_the_same_content_commits_nothing() -> None:
    bench = Bench()
    net_id = await bench.add("SDA", "U1.25", "blue")

    await bench.world.update_net(
        bench.revision.workspace_id,
        bench.revision.id,
        net_id,
        NetDraft.parse(" SDA ", "blue", "", "u1.gpio21"),
    )

    assert bench.world.work.commits == 1


async def test_a_net_is_removed_and_another_revisions_net_is_not_found() -> None:
    bench = Bench()
    net_id = await bench.add("SDA", "U1.25")

    with pytest.raises(NetNotFoundError):
        await bench.world.remove_net(bench.revision.workspace_id, bench.revision.id, NetId(uuid7()))
    await bench.world.remove_net(bench.revision.workspace_id, bench.revision.id, net_id)

    assert bench.world.work.nets.saved == {}
    assert bench.world.work.commits == 2


async def test_only_the_new_references_parts_are_read() -> None:
    bench = Bench()
    net_id = await bench.add("SDA", "U1.25")
    bench.world.work.parts.asked.clear()

    await bench.world.update_net(
        bench.revision.workspace_id,
        bench.revision.id,
        net_id,
        NetDraft.parse("SDA", None, None, "U1.25, U2.SDA"),
    )

    # The edit's own resolution asks for U2's part alone; the answer's view asks for the BOM's.
    assert bench.world.work.parts.asked[0] == (bench.bme280,)


async def test_deleting_the_revision_takes_its_nets() -> None:
    bench = Bench()
    await bench.add("SDA", "U1.25")
    await bench.world.work.revisions.remove(bench.revision)

    assert bench.world.work.nets.saved == {}


async def test_a_view_answers_the_boms_designators_parts_and_pins() -> None:
    bench = Bench()

    view = await bench.world.get_netlist(bench.revision.workspace_id, bench.revision.id)

    assert view.editable
    assert set(view.parts) == {bench.esp32, bench.bme280, bench.resistor}
    assert set(view.pins) == {bench.esp32, bench.bme280}


# Property 9: a fork carries its source's netlist, second, and each copy resolves as its source.
@pytest.mark.parametrize("status", [RevisionStatus.DRAFT, *LOCKED])
async def test_a_fork_carries_the_netlist(status: RevisionStatus) -> None:
    bench = Bench()
    await bench.add("SDA", "U1.SDA, U2.SDA, R1.2", "blue")
    await bench.add("SCL", "U1.SCL, U2.4")
    bench.remove_line("R1, R2")
    bench.revision.status = status

    fork = await bench.world.fork_revision(
        bench.revision.workspace_id, bench.revision.id, NewRevision()
    )

    source = await bench.world.get_netlist(bench.revision.workspace_id, bench.revision.id)
    copied = await bench.world.get_netlist(bench.revision.workspace_id, fork.id)
    assert [net.content for net in copied.netlist.nets] == [
        net.content for net in source.netlist.nets
    ]
    assert {net.id for net in copied.netlist.nets}.isdisjoint(
        {net.id for net in source.netlist.nets}
    )
    for net in source.netlist.nets:
        for reference in net.content.pins:
            assert source.resolution(reference).state == copied.resolution(reference).state


@pytest.mark.parametrize("status", [RevisionStatus.DRAFT, *LOCKED])
async def test_findings_come_with_the_view_whatever_the_status(status: RevisionStatus) -> None:
    # 12-wiring-validation requirements 1.1, 1.5 and 6.3: U1.25 in two nets is an error, and
    # the resistor, which has no pinout, a warning.
    bench = Bench()
    await bench.add("SDA", "U1.25, R1.2")
    await bench.add("SDA2", "U1.25")
    bench.revision.status = status

    view = await bench.world.get_netlist(bench.revision.workspace_id, bench.revision.id)

    codes = [(finding.code, finding.severity) for finding in view.findings()]
    assert codes == [
        (FindingCode.PIN_REUSED, Severity.ERROR),
        (FindingCode.NO_PINOUT, Severity.WARNING),
    ]
    summary = view.summary()
    assert (summary.errors, summary.warnings) == (1, 1)


async def test_a_revision_with_wiring_errors_is_reserved_as_any_other() -> None:
    # 12-wiring-validation requirement 6.1: findings never block a reserve.
    bench = Bench()
    await bench.add("SDA", "U1.25, R1.2")
    await bench.add("SCL", "U1.25")
    stock = bench.world.work.stock
    for part_id, on_hand in ((bench.esp32, 1), (bench.bme280, 1), (bench.resistor, 2)):
        stock.hold_lot(
            part_id, location_id=LocationId(uuid7()), location_code="WX-L-0001", on_hand=on_hand
        )

    reserved = await bench.world.reserve_revision(
        bench.revision.workspace_id, bench.revision.id, []
    )

    assert reserved.status is RevisionStatus.RESERVED
