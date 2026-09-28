from dataclasses import dataclass, field
from datetime import timedelta

import anyio
import pytest
from hypothesis import given
from hypothesis import strategies as st

from support.bom import a_line, boms
from support.projects import BENCH, CopyFailedError, FailingContent, World
from wiredex.projects.application.bom import CopyBomLines
from wiredex.projects.application.ports import NewRevision
from wiredex.projects.domain.bom import BomLine
from wiredex.projects.domain.revision import Revision
from wiredex.projects.domain.values import PartId, RevisionId, RevisionStatus

pytestmark = pytest.mark.anyio


@dataclass
class LinesSeen:
    """A content registered after the copy: it records the source it was given, how many
    lines the fork already held when its own turn came, and how many commits had happened."""

    world: World
    seen: list[tuple[RevisionId, int, int]] = field(default_factory=list)

    async def copy(self, source: Revision, target: Revision) -> None:
        bom = await self.world.work.bom_lines.of_revision(target.id)
        self.seen.append((source.id, len(bom.lines), self.world.work.commits))


def _held(world: World, *lines: BomLine) -> None:
    for line in lines:
        world.work.bom_lines.saved[line.id] = line


def _lines(world: World, revision: Revision) -> list[BomLine]:
    stored = world.work.bom_lines.saved.values()
    return sorted(
        (line for line in stored if line.revision_id == revision.id),
        key=lambda line: (line.created_at, line.id),
    )


@pytest.mark.parametrize("status", [RevisionStatus.DRAFT, RevisionStatus.BUILT])
async def test_a_fork_carries_its_sources_lines_in_order(status: RevisionStatus) -> None:
    world = World()
    project = world.hold_project("Weather station", revision=None)
    source = world.hold_revision(project, "A", status=status)
    sensor, resistor, wire = (
        world.parts.hold("BME280"),
        world.parts.hold("4k7"),
        world.parts.hold("Wire"),
    )
    held = (
        a_line(source, sensor, "U1"),
        a_line(source, resistor, "R1, R2", minutes=1),
        a_line(source, wire, quantity=1, minutes=2),
    )
    _held(world, *held)
    world.clock.advance(timedelta(hours=1))

    fork = await world.fork_revision(BENCH, source.id, NewRevision())

    copies = _lines(world, fork)
    assert [line.content for line in copies] == [line.content for line in held]
    assert all(line.revision_id == fork.id for line in copies)
    assert all(line.created_at == fork.created_at for line in copies)
    assert not {line.id for line in copies} & {line.id for line in held}
    assert _lines(world, source) == list(held)
    assert world.work.commits == 1


async def test_an_empty_bom_copies_nothing() -> None:
    world = World()
    project = world.hold_project("Weather station")
    source = next(iter(world.work.revisions.saved.values()))

    fork = await world.fork_revision(BENCH, source.id, NewRevision())

    assert _lines(world, fork) == []
    assert world.work.bom_lines.saved == {}
    assert project.id == fork.project_id


async def test_the_copy_is_registered_first() -> None:
    world = World()

    (first,) = world.work.revision_contents

    assert isinstance(first, CopyBomLines)


async def test_a_content_failing_after_the_copy_means_no_commit() -> None:
    world = World()
    project = world.hold_project("Weather station", revision=None)
    source = world.hold_revision(project, "A")
    _held(world, a_line(source, world.parts.hold("BME280"), "U1"))
    world.work.revision_contents = (*world.work.revision_contents, FailingContent())

    with pytest.raises(CopyFailedError):
        await world.fork_revision(BENCH, source.id, NewRevision())

    assert world.work.commits == 0


# --- Property 9: a fork carries its source's BOM, first -------------------------------------


@given(
    status=st.sampled_from(RevisionStatus),
    after=st.integers(0, 3),
    data=st.data(),
)
def test_a_fork_carries_its_sources_bom_first(
    status: RevisionStatus, after: int, data: st.DataObject
) -> None:
    """Property 9: a fork carries its source's BOM, first.

    For any project, any source revision in any of the four statuses with any BOM, and any
    contents registered after the copy, forking gives the fork lines whose contents equal the
    source's, line for line and in order, each with an id of its own and on the fork; leaves
    the source's BOM as it was; runs the copy before every other content, which finds the
    fork's lines already there; and commits once.

    **Validates: Requirements 7.1, 7.2, 7.3**
    """
    world = World()
    project = world.hold_project("Weather station", revision=None)
    source = world.hold_revision(project, "A", status=status)
    parts: list[PartId] = [world.parts.hold(f"Part {number}") for number in range(4)]
    bom = data.draw(boms(source, parts))

    async def scenario() -> None:
        _held(world, *bom.lines)
        watchers = [LinesSeen(world) for _ in range(after)]
        world.work.revision_contents = (*world.work.revision_contents, *watchers)
        world.clock.advance(timedelta(hours=1))

        fork = await world.fork_revision(BENCH, source.id, NewRevision())

        copies = _lines(world, fork)
        assert [line.content for line in copies] == [line.content for line in bom.lines]
        assert len({line.id for line in copies}) == len(copies)
        assert not {line.id for line in copies} & {line.id for line in bom.lines}
        assert all(
            (line.workspace_id, line.revision_id) == (fork.workspace_id, fork.id) for line in copies
        )
        assert _lines(world, source) == list(bom.lines)
        assert [watcher.seen for watcher in watchers] == [[(source.id, len(bom.lines), 0)]] * after
        assert world.work.commits == 1

    anyio.run(scenario)
