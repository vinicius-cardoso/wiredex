"""The build lifecycle use cases over the in-memory projects, stock and catalog fakes.

Task 11 wires the four transitions and three reads over fakes; the SQL adapters and the
one-transaction bootstrap are task 12. The fake `InMemoryBuildStock` keeps the invariant the
design states, so a reserve, cancel, build and dismantle move the same counts and units the
real ledger would, and `holdings`, `holdings_of_part` and `units_of` fold them back.

Properties 10 and 11 live here (design's Testing Strategy).
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from uuid import uuid7

import anyio
import pytest
from hypothesis import given
from hypothesis import strategies as st

from support.projects import (
    BENCH,
    NOW,
    InMemoryBuildStock,
    UnknownLocationInFakeError,
    World,
)
from wiredex.projects.application.ports import Lifecycle, NewRevision, RevisionRef
from wiredex.projects.domain.bom import BomLine, LineContent
from wiredex.projects.domain.designators import Designators
from wiredex.projects.domain.errors import RevisionHoldsStockError, RevisionNotFoundError
from wiredex.projects.domain.lifecycle import (
    EmptyBomError,
    ShortError,
    StockChangedError,
    Transition,
    TransitionNotAllowedError,
)
from wiredex.projects.domain.project import Project
from wiredex.projects.domain.values import (
    BomLineId,
    LocationId,
    PartId,
    RevisionId,
    RevisionStatus,
)

pytestmark = pytest.mark.anyio

DRAWER = LocationId(uuid7())
SHELF = LocationId(uuid7())


def a_line(world: World, revision_id: RevisionId, part_id: PartId, quantity: int) -> None:
    """A BOM line naming a part, straight into the store, so a test builds a BOM without the
    BOM use cases."""
    line = BomLine(
        BomLineId(uuid7()),
        BENCH,
        revision_id,
        LineContent.of(part_id, Designators.none(), quantity, None),
        NOW,
    )
    world.work.bom_lines.saved[line.id] = line


@dataclass
class Bench:
    """A seeded bench: a project with a draft revision, a BOM, catalog parts and stock."""

    world: World
    project: Project
    revision_id: RevisionId
    esp32: PartId
    resistor: PartId


def a_bench(*, resistor_on_hand: int = 40, esp32_on_hand: int = 1) -> Bench:
    """*Weather station* with a draft holding one ESP32 (a tracked board) and three 10k."""
    world = World()
    project = world.hold_project("Weather station")
    (revision,) = world.work.revisions.saved.values()

    esp32 = world.build_parts.hold("ESP32", tracked=True)
    resistor = world.build_parts.hold("Resistor 10k")

    a_line(world, revision.id, esp32, 1)
    a_line(world, revision.id, resistor, 3)

    codes = ["WX-U-0001"] if esp32_on_hand else []
    world.build_stock.hold_lot(
        esp32, location_id=DRAWER, location_code="WX-L-0004", on_hand=esp32_on_hand, units=codes
    )
    world.build_stock.hold_lot(
        resistor, location_id=DRAWER, location_code="WX-L-0003", on_hand=resistor_on_hand
    )
    return Bench(world, project, revision.id, esp32, resistor)


# --- Reserve --------------------------------------------------------------------------------


class TestReserve:
    async def test_reserves_a_draft_and_sets_its_stock_aside(self) -> None:
        # Requirements 2.1, 2.4, 2.6, 3.1: the board and three resistors are set aside.
        bench = a_bench()
        world = bench.world

        revision = await world.reserve_revision(BENCH, bench.revision_id, [])

        assert revision.status is RevisionStatus.RESERVED
        assert world.work.commits == 1
        holdings = await world.build_stock.holdings(bench.revision_id)
        assert {lot.part_id: lot.quantity for lot in holdings.reserved} == {
            bench.esp32: 1,
            bench.resistor: 3,
        }
        board = world.build_stock.unit("WX-U-0001")
        assert board.status == "reserved"
        assert board.revision_id == bench.revision_id

    async def test_a_repeated_reserve_is_refused_as_not_allowed(self) -> None:
        # Requirement 1.5: the second sees the status the first left.
        bench = a_bench()
        world = bench.world
        await world.reserve_revision(BENCH, bench.revision_id, [])
        commits = world.work.commits

        with pytest.raises(TransitionNotAllowedError) as caught:
            await world.reserve_revision(BENCH, bench.revision_id, [])
        assert caught.value.status is RevisionStatus.RESERVED
        assert world.work.commits == commits

    async def test_an_empty_bom_is_refused(self) -> None:
        # Requirement 2.3.
        world = World()
        world.hold_project("Empty")
        (revision,) = world.work.revisions.saved.values()

        with pytest.raises(EmptyBomError):
            await world.reserve_revision(BENCH, revision.id, [])
        assert revision.status is RevisionStatus.DRAFT
        assert world.work.commits == 0

    async def test_a_short_bom_is_refused_with_its_report(self) -> None:
        # Requirements 2.1, 2.2: not enough resistors.
        bench = a_bench(resistor_on_hand=1)
        world = bench.world

        with pytest.raises(ShortError) as caught:
            await world.reserve_revision(BENCH, bench.revision_id, [])
        assert caught.value.report.summary.short_parts == 1
        assert world.work.commits == 0
        # Nothing set aside.
        holdings = await world.build_stock.holdings(bench.revision_id)
        assert holdings.reserved == ()

    async def test_a_consumable_is_never_reserved_and_never_short(self) -> None:
        # Requirement 2.7, 7 (consumables): a BOM of a consumable reserves nothing and still
        # moves to reserved.
        world = World()
        world.hold_project("Weather station")
        (revision,) = world.work.revisions.saved.values()
        wire = world.build_parts.hold("Jumper wire", not_stocked=True)
        a_line(world, revision.id, wire, 5)

        reserved = await world.reserve_revision(BENCH, revision.id, [])

        assert reserved.status is RevisionStatus.RESERVED
        holdings = await world.build_stock.holdings(revision.id)
        assert holdings.reserved == ()

    async def test_a_named_board_is_reserved(self) -> None:
        # Requirements 3.2: the owner picks the board.
        bench = a_bench()
        world = bench.world
        board = world.build_stock.unit("WX-U-0001")

        await world.reserve_revision(BENCH, bench.revision_id, [board.unit_id])

        assert board.status == "reserved"
        assert board.revision_id == bench.revision_id

    async def test_stock_changed_is_refused(self) -> None:
        # Decision 12: a receipt between the two locks.
        bench = a_bench()
        world = bench.world
        world.build_stock.next_changed = True

        with pytest.raises(StockChangedError):
            await world.reserve_revision(BENCH, bench.revision_id, [])
        assert world.work.commits == 0


# --- Cancel, build, dismantle ---------------------------------------------------------------


class TestCancel:
    async def test_cancels_a_reservation_back_to_draft(self) -> None:
        # Requirements 4.1, 4.2: reserving then cancelling leaves the stock as it started.
        bench = a_bench()
        world = bench.world
        before = _stock_snapshot(world.build_stock)
        await world.reserve_revision(BENCH, bench.revision_id, [])

        revision = await world.cancel_reservation(BENCH, bench.revision_id)

        assert revision.status is RevisionStatus.DRAFT
        assert (await world.build_stock.holdings(bench.revision_id)).reserved == ()
        assert world.build_stock.unit("WX-U-0001").status == "in_stock"
        assert _stock_snapshot(world.build_stock) == before

    async def test_a_cancel_of_a_draft_is_refused(self) -> None:
        bench = a_bench()
        world = bench.world

        with pytest.raises(TransitionNotAllowedError):
            await world.cancel_reservation(BENCH, bench.revision_id)
        assert world.work.commits == 0


class TestBuild:
    async def test_builds_a_reservation_and_consumes_the_stock(self) -> None:
        # Requirement 5.1, 3.6: on hand drops, the board is in use.
        bench = a_bench()
        world = bench.world
        await world.reserve_revision(BENCH, bench.revision_id, [])

        revision = await world.build_revision(BENCH, bench.revision_id)

        assert revision.status is RevisionStatus.BUILT
        holdings = await world.build_stock.holdings(bench.revision_id)
        assert holdings.reserved == ()
        assert holdings.consumed == {bench.esp32: 1, bench.resistor: 3}
        assert world.build_stock.unit("WX-U-0001").status == "in_use"

    async def test_a_build_of_a_draft_is_refused(self) -> None:
        bench = a_bench()
        world = bench.world

        with pytest.raises(TransitionNotAllowedError):
            await world.build_revision(BENCH, bench.revision_id)
        assert world.work.commits == 0


class TestDismantle:
    async def test_dismantles_a_build_and_returns_its_parts(self) -> None:
        # Requirements 6.2, 6.3, 3.7: the parts and the board come back at the chosen location.
        bench = a_bench()
        world = bench.world
        await world.reserve_revision(BENCH, bench.revision_id, [])
        await world.build_revision(BENCH, bench.revision_id)

        revision = await world.dismantle_revision(BENCH, bench.revision_id, DRAWER)

        assert revision.status is RevisionStatus.DISMANTLED
        assert (await world.build_stock.holdings(bench.revision_id)).consumed == {}
        board = world.build_stock.unit("WX-U-0001")
        assert board.status == "in_stock"
        assert board.revision_id is None

    async def test_an_unknown_location_is_refused_before_any_write(self) -> None:
        # Requirement 6.1: the fake refuses a location it doesn't hold, as the adapter turns
        # into unknown_location; nothing is written.
        bench = a_bench()
        world = bench.world
        await world.reserve_revision(BENCH, bench.revision_id, [])
        await world.build_revision(BENCH, bench.revision_id)
        commits = world.work.commits

        with pytest.raises(UnknownLocationInFakeError):
            await world.dismantle_revision(BENCH, bench.revision_id, SHELF)
        assert world.work.commits == commits
        # Still built, still holding its consumption.
        (revision,) = [r for r in world.work.revisions.saved.values() if r.id == bench.revision_id]
        assert revision.status is RevisionStatus.BUILT


class TestNotFound:
    async def test_a_transition_of_a_revision_not_in_the_workspace_is_404(self) -> None:
        # Requirements 1.7, 11.3.
        world = World()
        world.hold_project("Weather station")

        with pytest.raises(RevisionNotFoundError):
            await world.reserve_revision(BENCH, RevisionId(uuid7()), [])
        assert world.work.commits == 0


# --- Deleting a held revision ----------------------------------------------------------------


class TestDelete:
    async def test_a_held_revision_is_refused(self) -> None:
        # Requirement 9.1: a reserved revision can't be deleted.
        bench = a_bench()
        world = bench.world
        world.hold_revision(bench.project, "B", minutes=1)  # a sibling, so it isn't the last
        await world.reserve_revision(BENCH, bench.revision_id, [])

        with pytest.raises(RevisionHoldsStockError, match="cancel the reservation"):
            await world.delete_revision(BENCH, bench.revision_id)
        assert bench.revision_id in world.work.revisions.saved

    async def test_a_dismantled_revision_is_deleted(self) -> None:
        # Requirement 9.2: a dismantled revision holds nothing, so it goes.
        bench = a_bench()
        world = bench.world
        world.hold_revision(bench.project, "B", minutes=1)
        await world.reserve_revision(BENCH, bench.revision_id, [])
        await world.build_revision(BENCH, bench.revision_id)
        await world.dismantle_revision(BENCH, bench.revision_id, DRAWER)

        await world.delete_revision(BENCH, bench.revision_id)

        assert bench.revision_id not in world.work.revisions.saved

    async def test_a_project_holding_a_built_revision_is_refused(self) -> None:
        # Requirement 9.3.
        bench = a_bench()
        world = bench.world
        await world.reserve_revision(BENCH, bench.revision_id, [])
        await world.build_revision(BENCH, bench.revision_id)

        with pytest.raises(RevisionHoldsStockError):
            await world.delete_project(BENCH, bench.project.id)
        assert bench.project.id in world.work.projects.saved

    async def test_a_fork_of_a_reserved_revision_holds_nothing(self) -> None:
        # Requirement 9.4: the fork is a draft with no holdings; the source keeps its own.
        bench = a_bench()
        world = bench.world
        await world.reserve_revision(BENCH, bench.revision_id, [])

        fork = await world.fork_revision(BENCH, bench.revision_id, NewRevision())

        assert fork.status is RevisionStatus.DRAFT
        assert (await world.build_stock.holdings(fork.id)).reserved == ()
        assert (await world.build_stock.holdings(bench.revision_id)).reserved != ()


# --- The reads -------------------------------------------------------------------------------


class TestReads:
    async def test_get_lifecycle_of_a_reserved_revision(self) -> None:
        # Requirement 10.1: status, transitions, deletable, and each part it holds.
        bench = a_bench()
        world = bench.world
        world.hold_revision(bench.project, "B", minutes=1)  # a sibling, so deletable can be True
        await world.reserve_revision(BENCH, bench.revision_id, [])

        life = await world.get_lifecycle(BENCH, bench.revision_id)

        assert isinstance(life, Lifecycle)
        assert life.status is RevisionStatus.RESERVED
        assert life.transitions == (Transition.CANCEL, Transition.BUILD)
        assert life.deletable is False  # a reserved revision holds stock
        by_part = {part.part_id: part for part in life.parts}
        esp32_facts = by_part[bench.esp32].facts
        assert esp32_facts is not None
        assert esp32_facts.name == "ESP32"
        assert sum(lot.quantity for lot in by_part[bench.resistor].reserved) == 3
        assert [unit.code for unit in by_part[bench.esp32].units] == ["WX-U-0001"]

    async def test_get_lifecycle_of_a_draft_holds_nothing_and_can_be_deleted(self) -> None:
        bench = a_bench()
        world = bench.world
        world.hold_revision(bench.project, "B", minutes=1)

        life = await world.get_lifecycle(BENCH, bench.revision_id)

        assert life.status is RevisionStatus.DRAFT
        assert life.transitions == (Transition.RESERVE,)
        assert life.deletable is True
        assert life.parts == ()

    async def test_get_lifecycle_of_a_revision_not_in_the_workspace_is_404(self) -> None:
        world = World()
        world.hold_project("Weather station")
        with pytest.raises(RevisionNotFoundError):
            await world.get_lifecycle(BENCH, RevisionId(uuid7()))

    async def test_get_revision_ref(self) -> None:
        # Requirement 10.2.
        bench = a_bench()
        world = bench.world

        ref = await world.get_revision_ref(BENCH, bench.revision_id)

        assert isinstance(ref, RevisionRef)
        assert ref.revision_id == bench.revision_id
        assert ref.project_id == bench.project.id
        assert ref.project_name == bench.project.name

    async def test_get_revision_ref_not_in_the_workspace_is_404(self) -> None:
        world = World()
        world.hold_project("Weather station")
        with pytest.raises(RevisionNotFoundError):
            await world.get_revision_ref(BENCH, RevisionId(uuid7()))

    async def test_list_part_holdings(self) -> None:
        # Requirement 10.4: each revision holding the resistor, with its ref.
        bench = a_bench()
        world = bench.world
        await world.reserve_revision(BENCH, bench.revision_id, [])

        holdings = await world.list_part_holdings(BENCH, bench.resistor)

        assert len(holdings) == 1
        assert holdings[0].revision.revision_id == bench.revision_id
        assert holdings[0].reserved == 3
        assert holdings[0].consumed == 0

    async def test_list_part_holdings_of_a_part_nothing_holds_is_empty(self) -> None:
        bench = a_bench()
        world = bench.world
        assert await world.list_part_holdings(BENCH, bench.resistor) == []


# --- Property 10 -----------------------------------------------------------------------------


def _stock_snapshot(stock: InMemoryBuildStock) -> tuple[object, ...]:
    """Every lot's counts and every unit's status/lot/revision, so a later comparison sees any
    change to the balances or the units."""
    lots = tuple(sorted((lot.lot_id, lot.on_hand, lot.reserved) for lot in stock.lots.values()))
    units = tuple(
        sorted(
            (unit.unit_id, unit.status, unit.lot_id, unit.revision_id)
            for unit in stock.units.values()
        )
    )
    return (lots, units)


def _revisions_snapshot(world: World) -> dict[RevisionId, tuple[object, ...]]:
    return {
        revision.id: (revision.status, revision.updated_at)
        for revision in world.work.revisions.saved.values()
    }


# The requests a property-10 run makes of a revision, and which refusal each should hit given
# where the revision stands.
_Action = str
_ACTIONS: Sequence[_Action] = (
    "reserve",
    "cancel",
    "build",
    "dismantle",
    "delete",
    "delete_project",
)


async def _run(world: World, bench: Bench, action: _Action, *, bad_location: bool) -> None:
    location = SHELF if bad_location else DRAWER
    match action:
        case "reserve":
            await world.reserve_revision(BENCH, bench.revision_id, [])
        case "cancel":
            await world.cancel_reservation(BENCH, bench.revision_id)
        case "build":
            await world.build_revision(BENCH, bench.revision_id)
        case "dismantle":
            await world.dismantle_revision(BENCH, bench.revision_id, location)
        case "delete":
            await world.delete_revision(BENCH, bench.revision_id)
        case _:
            await world.delete_project(BENCH, bench.project.id)


@given(
    status=st.sampled_from(list(RevisionStatus)),
    action=st.sampled_from(list(_ACTIONS)),
    short=st.booleans(),
    bad_location=st.booleans(),
    empty_bom=st.booleans(),
)
def test_property_10_a_refused_request_writes_nothing(
    status: RevisionStatus,
    action: _Action,
    short: bool,
    bad_location: bool,
    empty_bom: bool,
) -> None:
    """Property 10: a refused request writes nothing.

    For any revision, any transition or delete asked of it, and any BOM, stock, named units and
    location, a request that is refused, whichever the refusal, commits nothing and leaves the
    revision's status and last change, the ledger, the balances, the units and the project's
    revisions as they were.

    **Validates: Requirements 1.4, 2.2, 3.4, 3.5, 6.1, 9.1, 9.3**
    """

    async def scenario() -> None:
        bench = a_bench(resistor_on_hand=1 if short else 40)
        world = bench.world
        # A sibling, so a delete is never refused merely for being the last revision.
        world.hold_revision(bench.project, "B", minutes=1)
        await _place_in_status(bench, status, through_use_cases=not (short or empty_bom))
        if empty_bom:
            world.work.bom_lines.saved.clear()

        stock_before = _stock_snapshot(world.build_stock)
        revisions_before = _revisions_snapshot(world)
        commits_before = world.work.commits

        try:
            await _run(world, bench, action, bad_location=bad_location)
        except Exception:  # any refusal: nothing must have been written
            assert _stock_snapshot(world.build_stock) == stock_before
            assert _revisions_snapshot(world) == revisions_before
            assert world.work.commits == commits_before
        else:
            # It succeeded: at least one commit. Property 10 is about refusals, so a success
            # is simply not one of its cases.
            assert world.work.commits > commits_before

    anyio.run(scenario)


async def _place_in_status(
    bench: Bench, status: RevisionStatus, *, through_use_cases: bool
) -> None:
    """Put the bench's revision in `status`. When the stock allows it (a full, non-empty BOM),
    a reserved, built or dismantled revision is moved there through the transitions, so the
    fake's stock matches the status; otherwise the status is set directly."""
    world = bench.world
    (revision,) = [r for r in world.work.revisions.saved.values() if r.id == bench.revision_id]
    reachable = {RevisionStatus.RESERVED, RevisionStatus.BUILT, RevisionStatus.DISMANTLED}
    if not (through_use_cases and status in reachable):
        revision.status = status
        return
    await world.reserve_revision(BENCH, bench.revision_id, [])
    if status is RevisionStatus.RESERVED:
        return
    await world.build_revision(BENCH, bench.revision_id)
    if status is RevisionStatus.BUILT:
        return
    await world.dismantle_revision(BENCH, bench.revision_id, DRAWER)


# --- Property 11 -----------------------------------------------------------------------------


@given(
    make_esp32_consumable=st.booleans(),
    make_resistor_consumable=st.booleans(),
    transition=st.sampled_from(["cancel", "build", "dismantle"]),
)
def test_property_11_flags_changed_after_the_reserve_dont_change_what_goes_back(
    make_esp32_consumable: bool,
    make_resistor_consumable: bool,
    transition: str,
) -> None:
    """Property 11: flags changed after the reserve don't change what goes back.

    For any reservation and any change to the category flags of the BOM's parts made after the
    reserve, cancelling releases, building consumes and dismantling then returns exactly what
    the ledger says the revision holds, the same as with the flags unchanged: a part that
    became a consumable still comes back, and one that stopped being one is still not taken.

    **Validates: Requirements 5.3**
    """

    async def scenario() -> None:
        # Two runs from the same start: one with the flags left alone, one with them changed
        # after the reserve. The holdings that come back must match.
        expected = await _round_trip(transition, flip_esp32=False, flip_resistor=False)
        actual = await _round_trip(
            transition,
            flip_esp32=make_esp32_consumable,
            flip_resistor=make_resistor_consumable,
        )
        assert actual == expected

    anyio.run(scenario)


async def _round_trip(transition: str, *, flip_esp32: bool, flip_resistor: bool) -> object:
    """Reserve the bench's revision, flip the given parts' `not_stocked` flag, run the
    transition, and answer the stock's on-hand totals per part and each unit's status."""
    bench = a_bench()
    world = bench.world
    await world.reserve_revision(BENCH, bench.revision_id, [])

    if flip_esp32:
        _flip(world, bench.esp32)
    if flip_resistor:
        _flip(world, bench.resistor)

    if transition == "cancel":
        await world.cancel_reservation(BENCH, bench.revision_id)
    elif transition == "build":
        await world.build_revision(BENCH, bench.revision_id)
    else:
        await world.build_revision(BENCH, bench.revision_id)
        await world.dismantle_revision(BENCH, bench.revision_id, DRAWER)

    # Keyed by part name and unit code, not by the run's random ids, so two runs compare.
    names = {bench.esp32: "esp32", bench.resistor: "resistor"}
    lots = world.build_stock.lots.values()
    on_hand = tuple(sorted((names[lot.part_id], lot.on_hand, lot.reserved) for lot in lots))
    units = tuple(sorted((unit.code, unit.status) for unit in world.build_stock.units.values()))
    holdings = await world.build_stock.holdings(bench.revision_id)
    consumed = tuple(sorted((names[part], qty) for part, qty in holdings.consumed.items()))
    reserved = tuple(sorted((names[lot.part_id], lot.quantity) for lot in holdings.reserved))
    return (on_hand, units, consumed, reserved)


def _flip(world: World, part_id: PartId) -> None:
    facts = world.build_parts.facts[part_id]
    world.build_parts.facts[part_id] = replace(facts, not_stocked=not facts.not_stocked)
