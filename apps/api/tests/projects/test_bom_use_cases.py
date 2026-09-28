from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import timedelta
from uuid import uuid7

import pytest

from support.projects import BENCH, NOW, World
from wiredex.projects.application.ports import BomUse, NewBomLine
from wiredex.projects.application.revisions import lock_revision
from wiredex.projects.domain.bom import MAX_LINES, BomLine, BomNotes, LineContent, LineQuantity
from wiredex.projects.domain.designators import Designators
from wiredex.projects.domain.errors import (
    BomLineNotFoundError,
    DesignatorTakenError,
    InvalidLineQuantityError,
    QuantityMismatchError,
    RevisionContentLockedError,
    RevisionNotFoundError,
    TooManyLinesError,
    UnknownPartError,
)
from wiredex.projects.domain.filter import ProjectFilter
from wiredex.projects.domain.project import Project
from wiredex.projects.domain.revision import Revision
from wiredex.projects.domain.shortage import StockStatus
from wiredex.projects.domain.values import (
    BomLineId,
    PartId,
    ProjectId,
    ProjectName,
    RevisionId,
    RevisionStatus,
)

pytestmark = pytest.mark.anyio

LOCKED = [RevisionStatus.RESERVED, RevisionStatus.BUILT, RevisionStatus.DISMANTLED]


class Bench:
    """A world with a draft revision, a resistor and a sensor in the catalog, and a clock an
    hour on, so a write's touch shows."""

    def __init__(self) -> None:
        self.world = World()
        self.project = self.world.hold_project("Weather station")
        self.revision = next(iter(self.world.work.revisions.saved.values()))
        self.resistor = self.world.parts.hold("Resistor 4k7 0805")
        self.sensor = self.world.parts.hold("BME280")
        self.world.clock.advance(timedelta(hours=1))

    def hold_line(
        self,
        part_id: PartId,
        designators: str = "",
        quantity: int | None = None,
        *,
        revision: Revision | None = None,
        minutes: int = 0,
    ) -> BomLine:
        """A line written straight to the store, as a seed."""
        content = LineContent.of(part_id, Designators.parse(designators), quantity, None)
        line = BomLine.on(
            revision or self.revision,
            BomLineId(uuid7()),
            content,
            NOW + timedelta(minutes=minutes),
        )
        self.world.work.bom_lines.saved[line.id] = line
        return line

    def lines(self, revision: Revision | None = None) -> list[BomLine]:
        target = (revision or self.revision).id
        stored = self.world.work.bom_lines.saved.values()
        return sorted(
            (line for line in stored if line.revision_id == target),
            key=lambda line: (line.created_at, line.id),
        )


def _new(part_id: PartId, designators: str = "", quantity: int | None = None) -> NewBomLine:
    return NewBomLine(part_id, Designators.parse(designators), quantity)


# --- Adding -----------------------------------------------------------------------------------


async def test_a_line_is_added_after_the_revisions_others() -> None:
    bench = Bench()
    first = bench.hold_line(bench.sensor, "U1")

    line = await bench.world.add_bom_line(
        BENCH, bench.revision.id, NewBomLine(bench.resistor, Designators.parse("r1-4"), None)
    )

    assert bench.lines() == [first, line]
    assert line.content.quantity == LineQuantity(4)
    assert line.content.designators.text() == "R1–R4"
    assert (line.workspace_id, line.revision_id) == (BENCH, bench.revision.id)
    assert bench.world.work.commits == 1
    assert bench.world.work.opened_for == [BENCH]


async def test_adding_touches_the_revision_and_lifts_its_project() -> None:
    bench = Bench()
    later = bench.world.hold_project("Greenhouse controller", minutes=30)

    await bench.world.add_bom_line(BENCH, bench.revision.id, _new(bench.sensor, "U1"))

    assert bench.revision.updated_at == bench.world.clock.now()
    listed = await bench.world.list_projects(BENCH, ProjectFilter())
    assert [row.project.id for row in listed] == [bench.project.id, later.id]


async def test_the_part_is_asked_before_the_unit_of_work_opens() -> None:
    bench = Bench()

    with pytest.raises(UnknownPartError, match="isn't in the catalog"):
        await bench.world.add_bom_line(BENCH, bench.revision.id, _new(PartId(uuid7()), "R1"))

    # Refused before anything opened: no lock taken, no revision read, nothing written.
    assert bench.world.work.opened_for == []
    assert bench.world.work.projects.locks == []
    assert bench.lines() == []


async def test_the_part_is_asked_about_alone_for_the_callers_bench() -> None:
    bench = Bench()

    await bench.world.add_bom_line(BENCH, bench.revision.id, _new(bench.resistor, "R1"))

    assert bench.world.parts.asked == [(BENCH, (bench.resistor,))]


async def test_a_line_on_a_revision_that_doesnt_exist_is_not_found() -> None:
    bench = Bench()

    with pytest.raises(RevisionNotFoundError):
        await bench.world.add_bom_line(BENCH, RevisionId(uuid7()), _new(bench.resistor, "R1"))
    assert bench.world.work.commits == 0


@pytest.mark.parametrize("status", LOCKED)
async def test_nothing_is_added_to_a_revision_that_isnt_a_draft(status: RevisionStatus) -> None:
    bench = Bench()
    bench.revision.status = status

    with pytest.raises(RevisionContentLockedError, match=f"revision A is {status}"):
        await bench.world.add_bom_line(BENCH, bench.revision.id, _new(bench.resistor, "R1"))

    assert bench.lines() == []
    assert bench.world.work.commits == 0
    assert bench.revision.updated_at == NOW


async def test_a_taken_designator_is_refused_naming_the_line() -> None:
    bench = Bench()
    holder = bench.hold_line(bench.resistor, "R5-7")

    with pytest.raises(DesignatorTakenError, match="R7 is already on the line R5–R7") as refused:
        await bench.world.add_bom_line(BENCH, bench.revision.id, _new(bench.resistor, "R7, R8"))

    assert refused.value.line_id == holder.id
    assert bench.lines() == [holder]
    assert bench.world.work.commits == 0


async def test_the_same_designator_on_another_revision_is_fine() -> None:
    bench = Bench()
    other = bench.world.hold_revision(bench.project, "B")
    bench.hold_line(bench.resistor, "R1", revision=other)

    await bench.world.add_bom_line(BENCH, bench.revision.id, _new(bench.resistor, "R1"))

    assert len(bench.lines()) == 1


async def test_a_501st_line_is_refused() -> None:
    bench = Bench()
    for minutes in range(MAX_LINES):
        bench.hold_line(bench.resistor, quantity=1, minutes=minutes)

    with pytest.raises(TooManyLinesError):
        await bench.world.add_bom_line(BENCH, bench.revision.id, _new(bench.resistor, quantity=1))
    assert bench.world.work.commits == 0


@pytest.mark.parametrize(
    ("new", "error"),
    [
        ("mismatch", QuantityMismatchError),
        ("no quantity", InvalidLineQuantityError),
    ],
)
async def test_a_quantity_its_rules_refuse_writes_nothing(new: str, error: type[Exception]) -> None:
    bench = Bench()
    line = _new(bench.resistor, "R1-4", 5) if new == "mismatch" else _new(bench.resistor)

    with pytest.raises(error):
        await bench.world.add_bom_line(BENCH, bench.revision.id, line)
    assert bench.world.work.commits == 0


# --- Editing ----------------------------------------------------------------------------------


async def test_an_edit_replaces_everything_and_keeps_its_place() -> None:
    bench = Bench()
    first = bench.hold_line(bench.resistor, "R1-3")
    second = bench.hold_line(bench.sensor, "U1", minutes=1)
    edit = NewBomLine(bench.sensor, Designators.parse("R2-4"), None, BomNotes("divider"))

    edited = await bench.world.update_bom_line(BENCH, bench.revision.id, first.id, edit)

    assert bench.lines() == [edited, second]
    assert edited.id == first.id
    assert edited.content == edit.content()
    assert bench.revision.updated_at == bench.world.clock.now()
    assert bench.world.work.commits == 1


async def test_an_edit_that_changes_nothing_commits_nothing() -> None:
    bench = Bench()
    line = bench.hold_line(bench.resistor, "R1-3")

    same = await bench.world.update_bom_line(
        BENCH, bench.revision.id, line.id, _new(bench.resistor, "R3, R2, R1")
    )

    assert same == line
    assert bench.world.work.commits == 0
    assert bench.revision.updated_at == NOW


async def test_an_edit_asks_about_its_part_even_unchanged() -> None:
    bench = Bench()
    line = bench.hold_line(bench.resistor, "R1")
    del bench.world.parts.facts[bench.resistor]

    with pytest.raises(UnknownPartError):
        await bench.world.update_bom_line(
            BENCH, bench.revision.id, line.id, _new(bench.resistor, "R1, R2")
        )
    assert bench.world.work.opened_for == []


async def test_an_edit_onto_another_lines_designator_answers_409() -> None:
    bench = Bench()
    first = bench.hold_line(bench.resistor, "R1-3")
    bench.hold_line(bench.resistor, "R4", minutes=1)

    with pytest.raises(DesignatorTakenError, match="R4 is already on the line R4"):
        await bench.world.update_bom_line(
            BENCH, bench.revision.id, first.id, _new(bench.resistor, "R1-4")
        )
    assert bench.world.work.commits == 0


@pytest.mark.parametrize("status", LOCKED)
async def test_nothing_is_edited_on_a_revision_that_isnt_a_draft(
    status: RevisionStatus,
) -> None:
    bench = Bench()
    line = bench.hold_line(bench.resistor, "R1")
    bench.revision.status = status

    with pytest.raises(RevisionContentLockedError):
        await bench.world.update_bom_line(
            BENCH, bench.revision.id, line.id, _new(bench.resistor, "R2")
        )
    assert bench.lines() == [line]
    assert bench.world.work.commits == 0


# --- Removing ---------------------------------------------------------------------------------


async def test_a_line_is_removed_and_its_revision_touched() -> None:
    bench = Bench()
    line = bench.hold_line(bench.resistor, "R1-3")
    kept = bench.hold_line(bench.sensor, "U1", minutes=1)

    await bench.world.remove_bom_line(BENCH, bench.revision.id, line.id)

    assert bench.lines() == [kept]
    assert bench.revision.updated_at == bench.world.clock.now()
    assert bench.world.work.commits == 1


@pytest.mark.parametrize("status", LOCKED)
async def test_nothing_is_removed_from_a_revision_that_isnt_a_draft(
    status: RevisionStatus,
) -> None:
    bench = Bench()
    line = bench.hold_line(bench.resistor, "R1")
    bench.revision.status = status

    with pytest.raises(RevisionContentLockedError):
        await bench.world.remove_bom_line(BENCH, bench.revision.id, line.id)
    assert bench.lines() == [line]
    assert bench.world.work.commits == 0


# --- Not found --------------------------------------------------------------------------------


def _writes(bench: Bench, line_id: BomLineId) -> list[Callable[[RevisionId], Awaitable[object]]]:
    """The two writes that name a line, under whichever revision a test gives."""
    edit = _new(bench.resistor, "R9")
    return [
        lambda revision_id: bench.world.update_bom_line(BENCH, revision_id, line_id, edit),
        lambda revision_id: bench.world.remove_bom_line(BENCH, revision_id, line_id),
    ]


async def test_a_line_that_doesnt_exist_is_not_found() -> None:
    bench = Bench()
    for write in _writes(bench, BomLineId(uuid7())):
        with pytest.raises(BomLineNotFoundError):
            await write(bench.revision.id)
    assert bench.world.work.commits == 0


async def test_a_line_named_under_another_revision_is_not_found() -> None:
    bench = Bench()
    other = bench.world.hold_revision(bench.project, "B")
    line = bench.hold_line(bench.resistor, "R1", revision=other)

    for write in _writes(bench, line.id):
        with pytest.raises(BomLineNotFoundError):
            await write(bench.revision.id)
    assert bench.lines(other) == [line]


async def test_a_line_under_a_revision_that_doesnt_exist_is_not_found() -> None:
    bench = Bench()
    line = bench.hold_line(bench.resistor, "R1")

    for write in _writes(bench, line.id):
        with pytest.raises(RevisionNotFoundError):
            await write(RevisionId(uuid7()))
    with pytest.raises(RevisionNotFoundError):
        await bench.world.get_bom(BENCH, RevisionId(uuid7()))


# --- lock_revision ----------------------------------------------------------------------------


async def test_lock_revision_locks_the_project_before_it_reads_the_revision() -> None:
    bench = Bench()
    work = bench.world.work
    order: list[str] = []
    locked, get = work.projects.locked, work.revisions.get

    async def locking(project_id: ProjectId) -> Project | None:
        order.append("lock")
        return await locked(project_id)

    async def reading(revision_id: RevisionId) -> Revision | None:
        order.append("read")
        return await get(revision_id)

    work.projects.locked = locking  # type: ignore[method-assign]
    work.revisions.get = reading  # type: ignore[method-assign]

    revision = await lock_revision(work, bench.revision.id)

    assert revision is bench.revision
    assert order == ["lock", "read"]


async def test_lock_revision_is_a_404_for_a_revision_whose_project_went() -> None:
    bench = Bench()
    del bench.world.work.projects.saved[bench.project.id]

    with pytest.raises(RevisionNotFoundError):
        await lock_revision(bench.world.work, bench.revision.id)


@pytest.mark.parametrize("write", ["add", "update", "remove"])
async def test_every_write_takes_the_projects_lock(write: str) -> None:
    bench = Bench()
    line = bench.hold_line(bench.resistor, "R1")
    world, revision_id = bench.world, bench.revision.id

    if write == "add":
        await world.add_bom_line(BENCH, revision_id, _new(bench.sensor, "U1"))
    elif write == "update":
        await world.update_bom_line(BENCH, revision_id, line.id, _new(bench.resistor, "R2"))
    else:
        await world.remove_bom_line(BENCH, revision_id, line.id)

    assert world.work.projects.locks == [bench.project.id]


# --- Reading ----------------------------------------------------------------------------------


@pytest.mark.parametrize("status", list(RevisionStatus))
async def test_a_bom_says_whether_it_can_change(status: RevisionStatus) -> None:
    bench = Bench()
    bench.revision.status = status

    view = await bench.world.get_bom(BENCH, bench.revision.id)

    assert view.editable == (status is RevisionStatus.DRAFT)


async def test_a_bom_is_read_with_its_report() -> None:
    bench = Bench()
    resistors = bench.hold_line(bench.resistor, "R1-4")
    sensor = bench.hold_line(bench.sensor, "U1", minutes=1)
    bench.world.stock.available_by_part[bench.resistor] = 180

    view = await bench.world.get_bom(BENCH, bench.revision.id)

    assert view.revision is bench.revision
    assert view.bom.lines == (resistors, sensor)
    assert [(part.part_id, part.status) for part in view.report.parts] == [
        (bench.resistor, StockStatus.COVERED),
        (bench.sensor, StockStatus.SHORT),
    ]
    assert bench.world.work.commits == 0


async def test_the_report_follows_the_catalog_and_the_stock_between_two_reads() -> None:
    bench = Bench()
    bench.hold_line(bench.sensor, "U1")
    before = await bench.world.get_bom(BENCH, bench.revision.id)

    facts = bench.world.parts.facts
    facts[bench.sensor] = replace(facts[bench.sensor], name="BME280 breakout")
    bench.world.stock.available_by_part[bench.sensor] = 1
    after = await bench.world.get_bom(BENCH, bench.revision.id)

    assert before.report.parts[0].status is StockStatus.SHORT
    (sensor,) = after.report.parts
    assert sensor.part is not None
    assert sensor.part.name == "BME280 breakout"
    assert sensor.status is StockStatus.COVERED


async def test_a_flag_change_is_answered_at_the_next_read() -> None:
    bench = Bench()
    bench.hold_line(bench.sensor, "U1")
    facts = bench.world.parts.facts
    facts[bench.sensor] = replace(facts[bench.sensor], not_stocked=True)

    view = await bench.world.get_bom(BENCH, bench.revision.id)

    assert view.report.parts[0].status is StockStatus.NOT_STOCKED


@pytest.mark.parametrize("size", [1, 40])
async def test_a_bom_read_costs_the_same_whatever_its_size(size: int) -> None:
    bench = Bench()
    parts = [bench.world.parts.hold(f"Part {index}") for index in range(30)]
    for minutes in range(size):
        bench.hold_line(parts[minutes % len(parts)], quantity=1, minutes=minutes)
    work = bench.world.work

    await bench.world.get_bom(BENCH, bench.revision.id)

    assert (work.revisions.reads, work.bom_lines.reads) == (1, 1)
    assert len(bench.world.parts.asked) == 1
    assert len(bench.world.stock.asked) == 1
    asked = bench.world.parts.asked[0][1]
    assert len(asked) == len(set(asked)) == min(size, len(parts))


async def test_an_empty_bom_asks_neither_port() -> None:
    bench = Bench()

    view = await bench.world.get_bom(BENCH, bench.revision.id)

    assert view.bom.lines == ()
    assert view.report.summary.complete
    assert bench.world.parts.asked == []
    assert bench.world.stock.asked == []


# --- Part uses --------------------------------------------------------------------------------


async def test_part_uses_name_three_and_count_the_rest() -> None:
    bench = Bench()
    world = bench.world
    for name in ("Zeta", "alpha", "Beta", "Gamma"):
        project = world.hold_project(name)
        revision = next(
            r for r in world.work.revisions.saved.values() if r.project_id == project.id
        )
        bench.hold_line(bench.resistor, "R1", revision=revision)
    second = world.hold_revision(project, "B", minutes=5)
    bench.hold_line(bench.resistor, "R1", revision=second)
    # A second line of the same part on one revision is still one use.
    bench.hold_line(bench.resistor, "R2", revision=second, minutes=1)
    bench.hold_line(bench.sensor, "U1")

    found = await world.list_part_uses(BENCH, bench.resistor, 3)

    assert found.total == 5
    assert [(use.project_name, str(use.revision_label)) for use in found.uses] == [
        (ProjectName("alpha"), "A"),
        (ProjectName("Beta"), "A"),
        (ProjectName("Gamma"), "A"),
    ]
    assert isinstance(found.uses[0], BomUse)
    assert world.work.commits == 0


async def test_a_part_no_bom_names_has_no_uses() -> None:
    bench = Bench()

    found = await bench.world.list_part_uses(BENCH, bench.sensor, 3)

    assert (found.uses, found.total) == ((), 0)


# --- The cascades the fakes mirror -----------------------------------------------------------


async def test_deleting_a_revision_or_a_project_takes_its_lines() -> None:
    bench = Bench()
    other = bench.world.hold_revision(bench.project, "B", minutes=1)
    bench.hold_line(bench.resistor, "R1", revision=other)
    bench.hold_line(bench.resistor, "R1")

    await bench.world.delete_revision(BENCH, other.id)
    assert bench.lines(other) == []
    assert len(bench.lines()) == 1

    await bench.world.delete_project(BENCH, bench.project.id)
    assert bench.world.work.bom_lines.saved == {}
