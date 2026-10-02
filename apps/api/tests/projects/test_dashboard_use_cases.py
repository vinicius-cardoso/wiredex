"""The dashboard's projects reads over the in-memory fakes (18-dashboard).

The parts tied up in builds come from the build unit of work's stock, revisions and parts, in
one transaction; the fakes fold holdings the way the ledger does, so a reserve and a build
through 10's use cases show here as they would over Postgres. The statement counts and row-level
security are the integration tests' (test_dashboard_reads.py).
"""

from collections.abc import Mapping
from uuid import uuid7

import pytest

from support.projects import BENCH, NOW, World
from wiredex.projects.domain.bom import BomLine, LineContent
from wiredex.projects.domain.designators import Designators
from wiredex.projects.domain.values import BomLineId, LocationId, PartId, RevisionId

pytestmark = pytest.mark.anyio

DRAWER = LocationId(uuid7())


def a_draft(
    world: World, project: str, lines: Mapping[PartId, int], label: str = "A"
) -> RevisionId:
    """A project with one draft whose BOM needs the lines, written straight to the stores."""
    held = world.hold_project(project, revision=None)
    revision = world.hold_revision(held, label)
    for part_id, quantity in lines.items():
        line = BomLine(
            BomLineId(uuid7()),
            BENCH,
            revision.id,
            LineContent.of(part_id, Designators.none(), quantity, None),
            NOW,
        )
        world.work.bom_lines.saved[line.id] = line
    return revision.id


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
