"""The dashboard's projects reads over the in-memory fakes (18-dashboard).

The parts tied up in builds come from the build unit of work's stock, revisions and parts, in
one transaction; the fakes fold holdings the way the ledger does, so a reserve and a build
through 10's use cases show here as they would over Postgres. The shortages come from the
drafts and their BOMs, then the catalog and the stock, as a BOM read asks them. The statement
counts and row-level security are the integration tests' (test_dashboard_reads.py).
"""

from collections.abc import Mapping, Sequence
from types import TracebackType
from typing import Self
from uuid import uuid7

import pytest

from support.projects import (
    BENCH,
    NOW,
    FakePartLookup,
    FakeStockLevels,
    InMemoryProjectsUnitOfWork,
    World,
)
from wiredex.projects.application.dashboard import ListShortRevisions
from wiredex.projects.domain.bom import BomLine, LineContent
from wiredex.projects.domain.designators import Designators
from wiredex.projects.domain.shortage import PartFacts, StockStatus
from wiredex.projects.domain.values import (
    BomLineId,
    LocationId,
    PartId,
    RevisionId,
    RevisionStatus,
    WorkspaceId,
)

pytestmark = pytest.mark.anyio

DRAWER = LocationId(uuid7())


def a_draft(
    world: World, project: str, lines: Mapping[PartId, int], label: str = "A"
) -> RevisionId:
    """A project with one draft whose BOM needs the lines, written straight to the stores."""
    held = world.hold_project(project, revision=None)
    revision = world.hold_revision(held, label)
    lines_on(world, revision.id, lines)
    return revision.id


def lines_on(world: World, revision_id: RevisionId, lines: Mapping[PartId, int]) -> None:
    """BOM lines needing the parts, straight into the store."""
    for part_id, quantity in lines.items():
        line = BomLine(
            BomLineId(uuid7()),
            BENCH,
            revision_id,
            LineContent.of(part_id, Designators.none(), quantity, None),
            NOW,
        )
        world.work.bom_lines.saved[line.id] = line


def a_part(world: World, name: str, on_hand: int = 50) -> PartId:
    """A part the catalog holds, with a lot of it in the drawer."""
    part_id = world.build_parts.hold(name)
    world.build_stock.hold_lot(
        part_id, location_id=DRAWER, location_code="WX-L-0001", on_hand=on_hand
    )
    return part_id


class TestTiedUpParts:
    async def test_lists_each_held_part_with_the_revisions_holding_it(self) -> None:
        # Requirement 1.1: a reserved and a built revision both hold the resistor; the
        # capacitor only the reserved one.
        world = World()
        resistor = a_part(world, "Resistor 10k")
        capacitor = a_part(world, "Capacitor 100n")
        station = a_draft(world, "Weather station", {resistor: 3, capacitor: 2})
        robot = a_draft(world, "Robot", {resistor: 5})
        await world.reserve_revision(BENCH, station, [])
        await world.reserve_revision(BENCH, robot, [])
        await world.build_revision(BENCH, robot)

        tied_up = await world.list_tied_up_parts(BENCH)

        assert tied_up.more == 0
        first, second = tied_up.parts
        assert first.part_id == resistor
        assert first.facts is not None
        assert first.facts.name == "Resistor 10k"
        assert (first.reserved, first.consumed, first.tied_up) == (3, 5, 8)
        assert [
            (str(view.revision.project_name), view.reserved, view.consumed)
            for view in first.revisions
        ] == [("Robot", 0, 5), ("Weather station", 3, 0)]
        assert (second.part_id, second.reserved, second.consumed) == (capacitor, 2, 0)
        assert world.work.opened_for[-1] == BENCH
        assert world.work.commits == 3  # the two reserves and the build; the read commits none

    async def test_orders_the_most_tied_up_first_then_by_name_folded(self) -> None:
        # Requirement 1.2: two parts tied up as much read by name, case aside.
        world = World()
        zener = a_part(world, "Zener 5V1")
        anode = a_part(world, "anode cap")
        many = a_part(world, "Wire")
        revision = a_draft(world, "Weather station", {zener: 2, anode: 2, many: 9})
        await world.reserve_revision(BENCH, revision, [])

        tied_up = await world.list_tied_up_parts(BENCH)

        assert [part.part_id for part in tied_up.parts] == [many, anode, zener]

    async def test_a_limit_keeps_the_most_tied_up_and_counts_the_rest(self) -> None:
        # Requirement 1.3.
        world = World()
        parts = [a_part(world, f"Part {index}") for index in range(5)]
        revision = a_draft(
            world, "Weather station", {part: index + 1 for index, part in enumerate(parts)}
        )
        await world.reserve_revision(BENCH, revision, [])

        tied_up = await world.list_tied_up_parts(BENCH, 2)

        assert [part.part_id for part in tied_up.parts] == [parts[4], parts[3]]
        assert tied_up.more == 3

    async def test_a_part_the_catalog_no_longer_holds_comes_after_the_named_ones(self) -> None:
        # The design's decision 2: no name to sort by, so after those tied up as much.
        world = World()
        gone = a_part(world, "Aardvark sensor")
        kept = a_part(world, "Resistor 10k")
        revision = a_draft(world, "Weather station", {gone: 2, kept: 2})
        await world.reserve_revision(BENCH, revision, [])
        del world.build_parts.facts[gone]

        tied_up = await world.list_tied_up_parts(BENCH)

        assert [(part.part_id, part.facts is None) for part in tied_up.parts] == [
            (kept, False),
            (gone, True),
        ]

    async def test_a_cancel_and_a_dismantle_let_go_of_everything(self) -> None:
        # Requirement 1.4: what the ledger folds to nothing isn't tied up.
        world = World()
        resistor = a_part(world, "Resistor 10k")
        station = a_draft(world, "Weather station", {resistor: 3})
        robot = a_draft(world, "Robot", {resistor: 5})
        await world.reserve_revision(BENCH, station, [])
        await world.cancel_reservation(BENCH, station)
        await world.reserve_revision(BENCH, robot, [])
        await world.build_revision(BENCH, robot)
        await world.dismantle_revision(BENCH, robot, DRAWER)

        tied_up = await world.list_tied_up_parts(BENCH)

        assert tied_up.parts == ()
        assert tied_up.more == 0

    async def test_nothing_held_asks_neither_the_revisions_nor_the_catalog(self) -> None:
        world = World()
        a_part(world, "Resistor 10k")
        reads = world.work.revisions.reads

        tied_up = await world.list_tied_up_parts(BENCH)

        assert (tied_up.parts, tied_up.more) == ((), 0)
        assert world.build_stock.holdings_reads == 1
        assert world.work.revisions.reads == reads
        assert world.build_parts.asked == []

    async def test_reads_the_holdings_refs_and_facts_once_whatever_their_number(self) -> None:
        # Requirement 6.1, as far as the fakes can count it.
        world = World()
        parts = [a_part(world, f"Part {index}") for index in range(4)]
        for index, part in enumerate(parts):
            # Every draft needs the first part too, so it is held by four revisions.
            revision = a_draft(world, f"Project {index}", {parts[0]: 1, part: 2})
            await world.reserve_revision(BENCH, revision, [])
        reads = world.work.revisions.reads
        world.build_parts.asked.clear()

        tied_up = await world.list_tied_up_parts(BENCH)

        assert len(tied_up.parts) == 4
        assert world.build_stock.holdings_reads == 1
        assert world.work.revisions.reads == reads + 1
        assert len(world.build_parts.asked) == 1

    async def test_a_revision_whose_project_is_gone_is_left_out(self) -> None:
        # Between the holdings and the refs a project can go; its share goes with it, and a
        # part only it held is left out, as 10's part holdings leave it.
        world = World()
        resistor = a_part(world, "Resistor 10k")
        capacitor = a_part(world, "Capacitor 100n")
        station = a_draft(world, "Weather station", {resistor: 3})
        robot = a_draft(world, "Robot", {resistor: 5, capacitor: 1})
        await world.reserve_revision(BENCH, station, [])
        await world.reserve_revision(BENCH, robot, [])
        robot_project = world.work.revisions.saved[robot].project_id
        del world.work.projects.saved[robot_project]

        tied_up = await world.list_tied_up_parts(BENCH)

        [part] = tied_up.parts
        assert (part.part_id, part.reserved) == (resistor, 3)
        assert [view.revision.revision_id for view in part.revisions] == [station]


def a_stocked(world: World, name: str, available: int) -> PartId:
    """A part the catalog holds, `available` of it in stock, as the BOM's ports see it."""
    part_id = world.parts.hold(name)
    world.stock.available_by_part[part_id] = available
    return part_id


class TestShortRevisions:
    async def test_lists_a_short_draft_with_only_its_short_and_unknown_parts(self) -> None:
        # Requirement 2.1: the covered part is left out of the parts, kept in the summary.
        world = World()
        resistor = a_stocked(world, "Resistor 10k", 40)
        sensor = a_stocked(world, "BME280", 1)
        gone = PartId(uuid7())  # a part the catalog no longer holds
        station = a_draft(world, "Weather station", {resistor: 3, sensor: 2, gone: 1})

        short = await world.list_short_revisions(BENCH)

        assert short.more == 0
        [found] = short.revisions
        assert (found.revision.revision_id, str(found.revision.project_name)) == (
            station,
            "Weather station",
        )
        assert str(found.revision.label) == "A"
        assert [(part.part_id, part.status, part.short) for part in found.missing] == [
            (sensor, StockStatus.SHORT, 1),
            (gone, StockStatus.UNKNOWN_PART, 0),
        ]
        summary = found.report.summary
        assert (summary.parts, summary.short_parts, summary.unknown_parts) == (3, 1, 1)

    async def test_covered_consumable_and_empty_drafts_are_left_out(self) -> None:
        # Requirement 2.2.
        world = World()
        resistor = a_stocked(world, "Resistor 10k", 40)
        wire = world.parts.hold("Wire", not_stocked=True)
        a_draft(world, "Covered", {resistor: 3})
        a_draft(world, "Consumables", {wire: 10})
        a_draft(world, "Empty", {})

        short = await world.list_short_revisions(BENCH)

        assert (short.revisions, short.more) == ((), 0)

    async def test_only_drafts_are_listed(self) -> None:
        # A reserved or built revision already holds its stock (decision 4 of requirements).
        world = World()
        sensor = a_stocked(world, "BME280", 0)
        project = world.hold_project("Weather station", revision=None)
        for label, status in (("A", RevisionStatus.RESERVED), ("B", RevisionStatus.BUILT)):
            lines_on(world, world.hold_revision(project, label, status=status).id, {sensor: 1})
        draft = world.hold_revision(project, "C")
        lines_on(world, draft.id, {sensor: 1})

        short = await world.list_short_revisions(BENCH)

        assert [found.revision.revision_id for found in short.revisions] == [draft.id]

    async def test_a_draft_of_a_project_in_the_trash_is_left_out(self) -> None:
        # Requirement 2.4.
        world = World()
        sensor = a_stocked(world, "BME280", 0)
        kept = a_draft(world, "Weather station", {sensor: 1})
        trashed = a_draft(world, "Robot", {sensor: 1})
        robot = world.work.revisions.saved[trashed].project_id
        world.work.projects.saved[robot].move_to_trash(NOW)

        short = await world.list_short_revisions(BENCH)

        assert [found.revision.revision_id for found in short.revisions] == [kept]

    async def test_orders_by_project_name_folded_then_label_and_counts_the_rest(self) -> None:
        # Requirement 2.3.
        world = World()
        sensor = a_stocked(world, "BME280", 0)
        zeta = world.hold_project("Zeta", revision=None)
        for label in ("B", "A"):
            lines_on(world, world.hold_revision(zeta, label).id, {sensor: 1})
        a_draft(world, "alpha", {sensor: 1})

        short = await world.list_short_revisions(BENCH)
        page = await world.list_short_revisions(BENCH, 2)

        assert [
            (str(found.revision.project_name), str(found.revision.label))
            for found in short.revisions
        ] == [("alpha", "A"), ("Zeta", "A"), ("Zeta", "B")]
        assert [str(found.revision.label) for found in page.revisions] == ["A", "A"]
        assert page.more == 1

    async def test_each_draft_is_measured_against_all_the_stock(self) -> None:
        # Decision 5 of requirements: three available covers each draft needing two, so
        # neither is short, though both together would be.
        world = World()
        sensor = a_stocked(world, "BME280", 3)
        a_draft(world, "Weather station", {sensor: 2})
        a_draft(world, "Robot", {sensor: 2})

        assert (await world.list_short_revisions(BENCH)).revisions == ()

    async def test_asks_the_catalog_and_the_stock_once_for_every_part(self) -> None:
        # Requirement 6.2, as far as the fakes can count it: the drafts and their BOMs in one
        # read each, then one question to each module for every part at once.
        world = World()
        parts = [a_stocked(world, f"Part {index}", 0) for index in range(4)]
        for index, part in enumerate(parts):
            a_draft(world, f"Project {index}", {part: 1, parts[0]: 1})
        revision_reads = world.work.revisions.reads
        line_reads = world.work.bom_lines.reads

        short = await world.list_short_revisions(BENCH)

        assert len(short.revisions) == 4
        assert world.work.revisions.reads == revision_reads + 1
        assert world.work.bom_lines.reads == line_reads + 1
        [(asked_for, described)] = world.parts.asked
        [(stocked_for, counted)] = world.stock.asked
        assert (asked_for, stocked_for) == (BENCH, BENCH)
        assert sorted(described) == sorted(parts)
        assert sorted(counted) == sorted(parts)

    async def test_no_part_named_asks_neither_module(self) -> None:
        world = World()
        a_draft(world, "Empty", {})

        short = await world.list_short_revisions(BENCH)

        assert short.revisions == ()
        assert world.parts.asked == []
        assert world.stock.asked == []

    async def test_no_draft_reads_no_line(self) -> None:
        world = World()
        world.hold_project("Built", revision=None)
        line_reads = world.work.bom_lines.reads

        assert (await world.list_short_revisions(BENCH)).revisions == ()
        assert world.work.bom_lines.reads == line_reads

    async def test_the_other_modules_are_asked_after_the_projects_transaction(self) -> None:
        # Requirement 6.2: never two transactions open at once.
        world = World()
        tracked = _TrackedUnitOfWork(world.ids)
        world.work = tracked
        sensor = a_stocked(world, "BME280", 0)
        a_draft(world, "Weather station", {sensor: 1})
        parts = _AskedWhile(world.parts, tracked)
        stock = _CountedWhile(world.stock, tracked)

        short = await ListShortRevisions(tracked.for_workspace, parts, stock)(BENCH)

        assert len(short.revisions) == 1
        assert tracked.opened == 1
        assert parts.open_when_asked == [False]
        assert stock.open_when_asked == [False]


class _TrackedUnitOfWork(InMemoryProjectsUnitOfWork):
    """The in-memory unit of work, saying whether its transaction is open."""

    open = False
    opened = 0

    async def __aenter__(self) -> Self:
        self.open = True
        self.opened += 1
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.open = False


class _AskedWhile:
    """The catalog's lookup, recording whether projects' transaction was open when asked."""

    def __init__(self, parts: FakePartLookup, work: _TrackedUnitOfWork) -> None:
        self._parts = parts
        self._work = work
        self.open_when_asked: list[bool] = []

    async def describe(
        self, workspace_id: WorkspaceId, part_ids: Sequence[PartId]
    ) -> Mapping[PartId, PartFacts]:
        self.open_when_asked.append(self._work.open)
        return await self._parts.describe(workspace_id, part_ids)


class _CountedWhile:
    """The stock levels, recording whether projects' transaction was open when asked."""

    def __init__(self, stock: FakeStockLevels, work: _TrackedUnitOfWork) -> None:
        self._stock = stock
        self._work = work
        self.open_when_asked: list[bool] = []

    async def available(
        self, workspace_id: WorkspaceId, part_ids: Sequence[PartId]
    ) -> Mapping[PartId, int]:
        self.open_when_asked.append(self._work.open)
        return await self._stock.available(workspace_id, part_ids)
