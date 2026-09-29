"""Restoring a demo bench's sample projects, over the in-memory projects.

The samples go through the use cases the web calls, so these tests read what those wrote: the
projects with their details and tags, the revisions with their labels, summaries, notes and
sources (requirements 9.1 and 9.2), and their BOMs (09's requirements 10.2 and 10.3).

The sample parts are the fake catalog's, held under the sample catalog's names and flags,
and the fake stock holds what the inventory samples receive, so a BOM's report here reads as
it does in a demo bench.
"""

from collections.abc import Mapping, Sequence
from decimal import Decimal
from uuid import uuid7

import pytest

from support.projects import BENCH, World
from wiredex.catalog.application.demo import SAMPLE_CATALOG, SampleCategory, SamplePart
from wiredex.catalog.domain.pinout import VoltageLevel
from wiredex.projects.application.bom import GetBom
from wiredex.projects.application.demo import (
    SAMPLE_PROJECTS,
    RestoreSampleProjects,
    SampleBoms,
    SampleNets,
    SampleWrites,
)
from wiredex.projects.domain.designators import Designators
from wiredex.projects.domain.netlist import ResolutionState
from wiredex.projects.domain.pins import PartPins, PinFacts, PinNumber, PinType
from wiredex.projects.domain.project import Project
from wiredex.projects.domain.revision import Revision
from wiredex.projects.domain.shortage import PartFacts, StockStatus
from wiredex.projects.domain.values import LocationId, PartId, WorkspaceId
from wiredex.projects.domain.wiring import Severity

pytestmark = pytest.mark.anyio

# The sample catalog's parts a sample BOM names, with the flags their categories resolve.
TRACKED, CONSUMABLE = "ESP32-DevKitC", "Hook-up wire 22 AWG"
SAMPLE_PARTS = (
    TRACKED,
    "BME280",
    "AMS1117-3.3",
    "Resistor 4k7 0805",
    "Resistor 10k 0603",
    "Capacitor 100n 0603 X7R",
    "Capacitor 2u2 0805 X5R",
    CONSUMABLE,
)
# What the inventory samples receive of them, and where: the 4k7 across two lots summing to
# 180, the 10k in Drawer 3, the 100n in the Parts box, and one ESP32 unit (WX-U-0001) in the
# Lab. Each entry is (location code, on hand, unit codes). This is the sample stock the
# greenhouse's reserve draws on: three 10k, one 100n and the one board (decision 9).
LAB = LocationId(uuid7())
CABINET_A = LocationId(uuid7())
DRAWER_3 = LocationId(uuid7())
PARTS_BOX = LocationId(uuid7())
SAMPLE_STOCK: dict[str, tuple[tuple[LocationId, str, int, tuple[str, ...]], ...]] = {
    "Resistor 4k7 0805": ((CABINET_A, "WX-L-0002", 100, ()), (DRAWER_3, "WX-L-0003", 80, ())),
    "Resistor 10k 0603": ((DRAWER_3, "WX-L-0003", 200, ()),),
    "Capacitor 100n 0603 X7R": ((PARTS_BOX, "WX-L-0004", 100, ()),),
    TRACKED: ((LAB, "WX-L-0001", 1, ("WX-U-0001",)),),
}


class _LiveStockLevels:
    """Projects' `StockLevels` over the reserve's own `InMemoryBuildStock`, so the shortage
    report reads the same availability the reserve left behind: once the greenhouse holds the
    one ESP32, the weather stations report it short (requirement 12.3), exactly as production's
    one ledger answers both reads."""

    def __init__(self, world: World) -> None:
        self._stock = world.work.stock

    async def available(
        self, workspace_id: WorkspaceId, part_ids: Sequence[PartId]
    ) -> Mapping[PartId, int]:
        assert workspace_id == BENCH
        wanted = set(part_ids)
        available: dict[PartId, int] = {}
        for lot in self._stock.lots.values():
            if lot.part_id in wanted:
                available[lot.part_id] = available.get(lot.part_id, 0) + lot.available
        return available


class Demo:
    """An empty bench, a catalog holding the sample parts, the sample stock as units and lots,
    and the restore over them.

    The parts and stock live in the reserve's own fakes (`world.work.parts` and
    `world.work.stock`), the ones a transition writes; the catalog lookup and the shortage
    report read the same facts and the same live availability, so a report here reads as it
    does in a demo bench, the reserved board included.
    """

    def __init__(self, missing: tuple[str, ...] = ()) -> None:
        self.world = World()
        self.part_ids: dict[str, PartId] = {}
        for name in SAMPLE_PARTS:
            if name in missing:
                continue
            part_id = PartId(uuid7())
            facts = PartFacts(part_id, name, None, None, None, name == TRACKED, name == CONSUMABLE)
            self.part_ids[name] = part_id
            # The reserve's part lookup and the report's read the same facts.
            self.world.work.parts.facts[part_id] = facts
            self.world.parts.facts[part_id] = facts
            # The sample pinouts, as the catalog's restore writes them, for the nets to name.
            pins = _sample_pins(name)
            if pins is not None:
                self.world.work.pins.pinouts[part_id] = pins
        self._seed_stock()
        # The report reads the reserve's live stock, so a reservation shows in it.
        self.world.get_bom = GetBom(
            self.world.work.for_workspace, self.world.parts, _LiveStockLevels(self.world)
        )
        self._restore = RestoreSampleProjects(
            self.world.work.for_workspace,
            SampleWrites(
                self.world.create_project, self.world.update_revision, self.world.fork_revision
            ),
            SampleBoms(self.world.add_bom_line, self.sample_parts),
            SampleNets(self.world.get_netlist, self.world.add_net, self.world.update_net),
            self.world.reserve_revision,
        )

    def _seed_stock(self) -> None:
        """The bench's sample stock, fresh: the lots and the one ESP32 unit, none reserved."""
        self.world.work.stock.clear()
        for name, lots in SAMPLE_STOCK.items():
            if name not in self.part_ids:
                continue
            for location_id, code, on_hand, units in lots:
                self.world.work.stock.hold_lot(
                    self.part_ids[name],
                    location_id=location_id,
                    location_code=code,
                    on_hand=on_hand,
                    units=units,
                )

    async def restore(self, workspace_id: WorkspaceId) -> int:
        """A demo restore, inventory before projects as `_restore_benches` runs them: the
        stock is put back fresh first, then the projects, so a second reset reserves against a
        clean bench whatever the guest did to the stock (requirement 12.2)."""
        self._seed_stock()
        return await self._restore(workspace_id)

    async def sample_parts(self, workspace_id: WorkspaceId) -> Mapping[str, PartId]:
        """What the composition root reads from the catalog: the bench's parts by name."""
        assert workspace_id == BENCH
        return self.part_ids

    async def netlist(self, project: str, label: str) -> dict[str, str]:
        """A sample revision's nets by name, each as its canonical pin text."""
        revision = self.revisions(self.projects()[project])[label]
        view = await self.world.get_netlist(BENCH, revision.id)
        return {str(net.content.name): net.content.pins.text() for net in view.netlist.nets}

    async def states(self, project: str, label: str) -> list[ResolutionState]:
        """What every reference of a sample revision's netlist resolves to."""
        revision = self.revisions(self.projects()[project])[label]
        view = await self.world.get_netlist(BENCH, revision.id)
        return [
            view.resolution(reference).state
            for net in view.netlist.nets
            for reference in net.content.pins
        ]

    async def findings(self, project: str, label: str) -> list[tuple[Severity, str | None]]:
        """A sample revision's wiring findings: each one's severity and the part it names."""
        revision = self.revisions(self.projects()[project])[label]
        view = await self.world.get_netlist(BENCH, revision.id)
        return [
            (finding.severity, None if finding.part is None else finding.part.name)
            for finding in view.findings()
        ]

    def names(self) -> dict[PartId, str]:
        return {part_id: name for name, part_id in self.part_ids.items()}

    def bom(self, project: str, label: str) -> list[tuple[str, str, int, str | None]]:
        """A sample revision's lines as the BOM table shows them: designators, part,
        quantity and notes, in order."""
        revision = self.revisions(self.projects()[project])[label]
        stored = self.world.work.bom_lines.saved.values()
        lines = sorted(
            (line for line in stored if line.revision_id == revision.id),
            key=lambda line: (line.created_at, line.id),
        )
        names = self.names()
        return [
            (
                line.content.designators.text(),
                names[line.content.part_id],
                line.content.quantity.value,
                None if line.content.notes is None else str(line.content.notes),
            )
            for line in lines
        ]

    async def report(self, project: str, label: str) -> dict[str, tuple[StockStatus, int]]:
        """Each part of a sample revision's BOM: its status and how many are short."""
        revision = self.revisions(self.projects()[project])[label]
        view = await self.world.get_bom(BENCH, revision.id)
        names = self.names()
        return {names[part.part_id]: (part.status, part.short) for part in view.report.parts}

    def projects(self) -> dict[str, Project]:
        return {p.name.value: p for p in self.world.work.projects.saved.values()}

    def revisions(self, project: Project) -> dict[str, Revision]:
        saved = self.world.work.revisions.saved.values()
        return {r.label.value: r for r in saved if r.project_id == project.id}

    def snapshot(self) -> list[tuple[object, ...]]:
        """The bench as a guest reads it, without the ids a restore mints anew."""
        rows: list[tuple[object, ...]] = []
        for name, project in sorted(self.projects().items()):
            revisions = self.revisions(project)
            labels = {revision.id: label for label, revision in revisions.items()}
            rows.append(
                (
                    name,
                    str(project.description),
                    project.tags.texts(),
                    sorted(
                        (
                            label,
                            str(revision.summary),
                            None if revision.notes is None else str(revision.notes),
                            revision.status,
                            None if revision.forked_from is None else labels[revision.forked_from],
                        )
                        for label, revision in revisions.items()
                    ),
                    {label: self.bom(name, label) for label in sorted(revisions)},
                )
            )
        return rows


@pytest.fixture
def demo() -> Demo:
    return Demo()


async def test_a_restore_writes_the_two_sample_projects(demo: Demo) -> None:
    restored = await demo.restore(BENCH)

    projects = demo.projects()
    assert restored == len(projects) == 2
    station = projects["Weather station"]
    assert str(station.description).startswith("A BME280 on an ESP32")
    assert station.tags.texts() == ("esp32", "i2c", "outdoor")
    greenhouse = projects["Greenhouse controller"]
    assert str(greenhouse.description) == "Waters the tomatoes when the soil dries out."
    assert greenhouse.tags.texts() == ("esp32", "relay")


async def test_the_weather_stations_b_is_forked_from_its_a(demo: Demo) -> None:
    await demo.restore(BENCH)

    revisions = demo.revisions(demo.projects()["Weather station"])
    assert set(revisions) == {"A", "B"}
    a, b = revisions["A"], revisions["B"]
    assert (str(a.summary), a.notes, a.forked_from) == ("breadboard", None, None)
    assert str(b.summary) == "perfboard"
    assert b.forked_from == a.id
    assert b.notes is not None
    assert "off the board" in str(b.notes)
    greenhouse = demo.revisions(demo.projects()["Greenhouse controller"])
    assert [(label, str(r.summary)) for label, r in greenhouse.items()] == [("A", "breadboard")]
    # The greenhouse's A is reserved by the restore; every other revision stays a draft.
    assert greenhouse["A"].status == "reserved"
    assert (a.status, b.status) == ("draft", "draft")


async def test_a_second_restore_gives_the_same_projects(demo: Demo) -> None:
    await demo.restore(BENCH)
    first = demo.snapshot()

    await demo.restore(BENCH)

    assert demo.snapshot() == first
    assert len(demo.world.work.revisions.saved) == 3


async def test_a_restore_takes_what_a_guest_added_and_puts_back_what_they_changed(
    demo: Demo,
) -> None:
    await demo.restore(BENCH)
    sample = demo.snapshot()
    demo.world.hold_project("Their robot", tags=["servo"])
    greenhouse = demo.projects()["Greenhouse controller"]
    await demo.world.work.projects.remove(greenhouse)
    station = demo.projects()["Weather station"]
    demo.world.hold_revision(station, "C")

    await demo.restore(BENCH)

    assert "Their robot" not in demo.projects()
    assert demo.snapshot() == sample


async def test_a_restore_touches_only_the_bench_it_was_asked_for(demo: Demo) -> None:
    await demo.restore(BENCH)

    assert set(demo.world.work.opened_for) == {BENCH}
    assert all(p.workspace_id == BENCH for p in demo.projects().values())


def test_every_sample_fork_starts_from_an_earlier_sample_revision() -> None:
    """The data itself: a fork's source is a label the project already holds by then."""
    for sample in SAMPLE_PROJECTS:
        labels = [sample.first.label]
        for fork in sample.forks:
            assert fork.source in labels
            labels.append(fork.label)
        assert len(set(labels)) == len(labels)


# --- The sample BOMs (09's requirement 10.2) ---------------------------------------------------

WEATHER_STATION_A = [
    ("U1", "ESP32-DevKitC", 1, None),
    ("U2", "BME280", 1, None),
    ("R1, R2", "Resistor 4k7 0805", 2, "I²C pull-ups"),
    ("C1", "Capacitor 100n 0603 X7R", 1, "BME280 decoupling"),
    ("", "Hook-up wire 22 AWG", 1, "about 2 m of jumpers"),
]


async def test_every_sample_revision_gets_its_lines(demo: Demo) -> None:
    await demo.restore(BENCH)

    assert demo.bom("Weather station", "A") == WEATHER_STATION_A
    assert demo.bom("Greenhouse controller", "A") == [
        ("U1", "ESP32-DevKitC", 1, None),
        ("R1–R3", "Resistor 10k 0603", 3, "soil probe divider and pull-downs"),
        ("C1", "Capacitor 100n 0603 X7R", 1, None),
    ]


async def test_the_fork_copies_as_lines_and_then_adds_its_own(demo: Demo) -> None:
    # A's lines are added before B is forked, so the fork copies them, in order; B's own
    # come after: the regulator and its two capacitors.
    await demo.restore(BENCH)

    assert demo.bom("Weather station", "B") == [
        *WEATHER_STATION_A,
        ("U3", "AMS1117-3.3", 1, "3V3 from the battery"),
        ("C2, C3", "Capacitor 2u2 0805 X5R", 2, "regulator input and output"),
    ]


async def test_the_sample_reports_show_the_esp32_reserved_for_the_greenhouse(demo: Demo) -> None:
    # After the restore reserves the greenhouse, the bench's one ESP32 is set aside for it, so
    # both weather stations report their ESP32 short (requirement 12.3), on top of the parts
    # the sample stock never held: the BME280, and B's regulator and its two 2u2.
    await demo.restore(BENCH)

    station_a = await demo.report("Weather station", "A")
    assert {
        name: found for name, found in station_a.items() if found[0] is not StockStatus.COVERED
    } == {
        TRACKED: (StockStatus.SHORT, 1),
        "BME280": (StockStatus.SHORT, 1),
        CONSUMABLE: (StockStatus.NOT_STOCKED, 0),
    }
    station_b = await demo.report("Weather station", "B")
    assert station_b[TRACKED] == (StockStatus.SHORT, 1)
    assert station_b["AMS1117-3.3"] == (StockStatus.SHORT, 1)
    assert station_b["Capacitor 2u2 0805 X5R"] == (StockStatus.SHORT, 2)
    assert station_b["BME280"] == (StockStatus.SHORT, 1)


async def test_the_restore_reserves_the_greenhouses_board_and_parts(demo: Demo) -> None:
    # Requirement 12.1: the greenhouse's A is reserved through the reserve use case, setting
    # aside the ESP32 board and its other parts. The board's unit is now held for it, and its
    # holdings are the three 10k, the one 100n and the ESP32.
    await demo.restore(BENCH)

    greenhouse = demo.revisions(demo.projects()["Greenhouse controller"])["A"]
    assert greenhouse.status == "reserved"
    board = demo.world.work.stock.unit("WX-U-0001")
    assert (board.status, board.revision_id) == ("reserved", greenhouse.id)
    holdings = await demo.world.work.stock.holdings(greenhouse.id)
    reserved_by_part = {lot.part_id: lot.quantity for lot in holdings.reserved}
    assert reserved_by_part == {
        demo.part_ids["Resistor 10k 0603"]: 3,
        demo.part_ids["Capacitor 100n 0603 X7R"]: 1,
        demo.part_ids[TRACKED]: 1,
    }


async def test_a_second_restore_reserves_the_same_greenhouse(demo: Demo) -> None:
    # Requirement 12.2: whatever a guest did, a second reset puts the same reservation back.
    # Here the guest builds the greenhouse, then a reset restores it reserved again, off a
    # fresh bench and its one ESP32.
    await demo.restore(BENCH)
    greenhouse = demo.revisions(demo.projects()["Greenhouse controller"])["A"]
    await demo.world.build_revision(BENCH, greenhouse.id)

    await demo.restore(BENCH)

    restored = demo.revisions(demo.projects()["Greenhouse controller"])["A"]
    assert restored.status == "reserved"
    assert demo.world.work.stock.unit("WX-U-0001").status == "reserved"
    report = await demo.report("Weather station", "A")
    assert report[TRACKED] == (StockStatus.SHORT, 1)


async def test_a_line_whose_part_the_sample_catalog_lacks_is_skipped() -> None:
    demo = Demo(missing=("BME280",))

    await demo.restore(BENCH)

    assert [line[1] for line in demo.bom("Weather station", "A")] == [
        "ESP32-DevKitC",
        "Resistor 4k7 0805",
        "Capacitor 100n 0603 X7R",
        "Hook-up wire 22 AWG",
    ]


def test_every_sample_line_names_a_sample_part_and_its_designators_read() -> None:
    """The data itself: each line's part is one the sample catalog holds, and its
    designators are a list the editor would take."""
    lines = [
        line
        for sample in SAMPLE_PROJECTS
        for line in (*sample.first.lines, *(line for fork in sample.forks for line in fork.lines))
    ]
    assert {line.part for line in lines} == set(SAMPLE_PARTS)
    for line in lines:
        # Refused with a `ContentError` if the editor wouldn't take it; counted if it would.
        count = len(Designators.parse(line.designators))
        assert count or line.quantity == 1
    assert [line.part for line in lines if not line.designators] == [CONSUMABLE]


def _sample_pins(name: str) -> PartPins | None:
    """The sample catalog's pins for a part, in projects' words, as bootstrap translates them."""
    for part in _sample_parts(SAMPLE_CATALOG):
        if part.name == name and part.pins:
            return PartPins(
                tuple(
                    PinFacts(
                        PinNumber(pin.number),
                        pin.label,
                        PinType(pin.type.value),
                        tuple(pin.functions.split()),
                        None if pin.voltage is None else _volts(pin.voltage),
                    )
                    for pin in part.pins
                )
            )
    return None


def _sample_parts(categories: Sequence[SampleCategory]) -> list[SamplePart]:
    found: list[SamplePart] = []
    for category in categories:
        found += category.parts
        found += _sample_parts(category.children)
    return found


def _volts(text: str) -> Decimal:
    return VoltageLevel.parse(text).value


async def test_the_sample_revisions_are_wired_and_every_pin_is_real(demo: Demo) -> None:
    # 11-netlist-editor requirement 9: nets written through AddNet, resolving by number, label
    # and function; the resistors and capacitors, which have no pinout, unchecked.
    await demo.restore(BENCH)

    station_a = await demo.netlist("Weather station", "A")
    assert station_a == {
        "3V3": "C1.1, R1.1, R2.1, U1.1, U2.2, U2.6, U2.8",
        "GND": "C1.2, U1.14, U2.1, U2.5, U2.7",
        "SDA": "R1.2, U1.25, U2.3",
        "SCL": "R2.2, U1.22, U2.4",
    }
    states = await demo.states("Weather station", "A")
    assert ResolutionState.RESOLVED in states
    assert ResolutionState.UNCHECKED in states
    assert not any(state.unresolved for state in states)


async def test_the_fork_copies_the_nets_and_wires_its_regulator(demo: Demo) -> None:
    await demo.restore(BENCH)

    station_b = await demo.netlist("Weather station", "B")
    assert station_b["VBAT"] == "C2.1, U3.3"
    assert station_b["3V3"] == "C1.1, C3.1, R1.1, R2.1, U1.1, U2.2, U2.6, U2.8, U3.2"
    assert station_b["GND"] == "C1.2, C2.2, C3.2, U1.14, U2.1, U2.5, U2.7, U3.1"
    assert not any(state.unresolved for state in await demo.states("Weather station", "B"))


async def test_the_greenhouse_is_wired_before_it_is_reserved(demo: Demo) -> None:
    await demo.restore(BENCH)

    assert await demo.netlist("Greenhouse controller", "A") == {
        "3V3": "C1.1, R1.1, U1.1",
        "GND": "C1.2, R2.2, R3.2, U1.14",
        "SOIL": "R1.2, R2.1, U1.5",
        "PUMP": "R3.1, U1.10",
    }


async def test_the_sample_wiring_has_no_errors_and_a_warning_per_passive_part(demo: Demo) -> None:
    # 12-wiring-validation requirement 9.1: the sample netlists are clean; each part without a
    # pinout they wire is one warning, since its pins are taken by number.
    await demo.restore(BENCH)

    warned = {
        (project, label): await demo.findings(project, label)
        for project, label in (
            ("Weather station", "A"),
            ("Weather station", "B"),
            ("Greenhouse controller", "A"),
        )
    }

    assert warned == {
        ("Weather station", "A"): [
            (Severity.WARNING, "Capacitor 100n 0603 X7R"),
            (Severity.WARNING, "Resistor 4k7 0805"),
        ],
        ("Weather station", "B"): [
            (Severity.WARNING, "Capacitor 100n 0603 X7R"),
            (Severity.WARNING, "Capacitor 2u2 0805 X5R"),
            (Severity.WARNING, "Resistor 4k7 0805"),
        ],
        ("Greenhouse controller", "A"): [
            (Severity.WARNING, "Capacitor 100n 0603 X7R"),
            (Severity.WARNING, "Resistor 10k 0603"),
        ],
    }
