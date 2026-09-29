"""Restoring a demo bench's sample projects, over the in-memory projects.

The samples go through the use cases the web calls, so these tests read what those wrote: the
projects with their details and tags, the revisions with their labels, summaries, notes and
sources (requirements 9.1 and 9.2), and their BOMs (09's requirements 10.2 and 10.3).

The sample parts are the fake catalog's, held under the sample catalog's names and flags,
and the fake stock holds what the inventory samples receive, so a BOM's report here reads as
it does in a demo bench.
"""

from collections.abc import Mapping

import pytest

from support.projects import BENCH, World
from wiredex.projects.application.demo import SAMPLE_PROJECTS, RestoreSampleProjects, SampleBoms
from wiredex.projects.domain.designators import Designators
from wiredex.projects.domain.project import Project
from wiredex.projects.domain.revision import Revision
from wiredex.projects.domain.shortage import StockStatus
from wiredex.projects.domain.values import PartId, WorkspaceId

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
# What the inventory samples receive of them: the 4k7 across two lots, and one ESP32 unit.
SAMPLE_STOCK = {
    "Resistor 4k7 0805": 180,
    "Resistor 10k 0603": 200,
    "Capacitor 100n 0603 X7R": 100,
    TRACKED: 1,
}


class Demo:
    """An empty bench, a catalog holding the sample parts, the sample stock, and the restore
    over them."""

    def __init__(self, missing: tuple[str, ...] = ()) -> None:
        self.world = World()
        self.part_ids: dict[str, PartId] = {
            name: self.world.parts.hold(
                name, tracked=name == TRACKED, not_stocked=name == CONSUMABLE
            )
            for name in SAMPLE_PARTS
            if name not in missing
        }
        for name, count in SAMPLE_STOCK.items():
            if name in self.part_ids:
                self.world.stock.available_by_part[self.part_ids[name]] = count
        self.restore = RestoreSampleProjects(
            self.world.work.for_workspace,
            self.world.create_project,
            self.world.update_revision,
            self.world.fork_revision,
            SampleBoms(self.world.add_bom_line, self.sample_parts),
        )

    async def sample_parts(self, workspace_id: WorkspaceId) -> Mapping[str, PartId]:
        """What the composition root reads from the catalog: the bench's parts by name."""
        assert workspace_id == BENCH
        return self.part_ids

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
    assert all(r.status == "draft" for r in demo.world.work.revisions.saved.values())


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


async def test_the_sample_reports_show_what_the_shortage_report_is_for(demo: Demo) -> None:
    # Against the sample stock: the one ESP32 unit covers each revision on its own, the
    # resistors and the 100n are stocked, and no BME280, AMS1117 or 2u2 is.
    await demo.restore(BENCH)

    station_a = await demo.report("Weather station", "A")
    assert {
        name: found for name, found in station_a.items() if found[0] is not StockStatus.COVERED
    } == {
        "BME280": (StockStatus.SHORT, 1),
        CONSUMABLE: (StockStatus.NOT_STOCKED, 0),
    }
    station_b = await demo.report("Weather station", "B")
    assert station_b["AMS1117-3.3"] == (StockStatus.SHORT, 1)
    assert station_b["Capacitor 2u2 0805 X5R"] == (StockStatus.SHORT, 2)
    assert station_b["BME280"] == (StockStatus.SHORT, 1)
    greenhouse = await demo.report("Greenhouse controller", "A")
    assert set(greenhouse.values()) == {(StockStatus.COVERED, 0)}


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
