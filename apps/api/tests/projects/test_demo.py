"""Restoring a demo bench's sample projects, over the in-memory projects.

The samples go through the use cases the web calls, so these tests read what those wrote: the
projects with their details and tags, and the revisions with their labels, summaries, notes and
sources (requirements 9.1 and 9.2).
"""

import pytest

from support.projects import BENCH, World
from wiredex.projects.application.demo import SAMPLE_PROJECTS, RestoreSampleProjects
from wiredex.projects.domain.project import Project
from wiredex.projects.domain.revision import Revision

pytestmark = pytest.mark.anyio


class Demo:
    """An empty bench and the restore over it."""

    def __init__(self) -> None:
        self.world = World()
        self.restore = RestoreSampleProjects(
            self.world.work.for_workspace,
            self.world.create_project,
            self.world.update_revision,
            self.world.fork_revision,
        )

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
