"""The boards a firmware runs on, over the in-memory firmware fakes (15-flash-log requirement 4,
decision 11): the units whose newest flash is one of its versions, neither retired nor gone, by
code.

The flashes are written straight to the store, as they were logged before their units were
retired or deleted, so a board's whole history is something a test can set.
"""

from dataclasses import replace
from datetime import datetime, timedelta
from uuid import UUID, uuid7

import anyio
import pytest
from hypothesis import given
from hypothesis import strategies as st

from support.firmware import BENCH, NOW, World
from wiredex.firmware.domain.errors import FirmwareNotFoundError
from wiredex.firmware.domain.flash import Flash
from wiredex.firmware.domain.values import FirmwareId, UnitId

pytestmark = pytest.mark.anyio


async def test_lists_each_board_whose_current_flash_is_the_firmwares_by_code() -> None:
    # Requirement 4.1: each with its version, when it was flashed, the revision holding it now
    # and the newer release. A board that moved on to another firmware runs this one no more,
    # and the revisions, recorded and holding, are asked for in one read.
    world = World()
    blink = world.hold_firmware("Pico blink")
    first = world.hold_version(blink, "1.0.0", released=True)
    second = world.hold_version(blink, "1.1.0", released=True)
    weather = world.hold_version(world.hold_firmware("Weather station"), "0.1.0", released=True)
    greenhouse = world.directory.hold("Greenhouse controller", "A")
    bench_test = world.directory.hold("Weather station", "A")
    late = world.units.hold("WX-U-0003", revision_id=greenhouse.revision_id)
    early = world.units.hold("WX-U-0001")
    moved_on = world.units.hold("WX-U-0002")
    flashed = world.hold_flash(replace(late, revision_id=bench_test.revision_id), first)
    world.hold_flash(early, first, flashed_at=NOW - timedelta(days=2))
    newest = world.hold_flash(early, second, flashed_at=NOW - timedelta(days=1))
    world.hold_flash(moved_on, second, flashed_at=NOW - timedelta(days=2))
    world.hold_flash(moved_on, weather, flashed_at=NOW - timedelta(days=1))

    boards = await world.list_boards(BENCH, blink.id)

    assert [(board.unit, board.current.entry.flash, board.newer_release) for board in boards] == [
        (early, newest, None),
        (late, flashed, second),
    ]
    assert [(board.revision, board.current.revision) for board in boards] == [
        (None, None),
        (greenhouse, bench_test),
    ]
    assert boards[1].current.entry.number == first.number
    assert world.directory.asked == [(greenhouse.revision_id, bench_test.revision_id)]
    assert world.work.commits == 0


async def test_leaves_out_retired_units_and_units_no_longer_in_the_workspace() -> None:
    # Requirement 4.2: a revision only they named isn't asked for.
    world = World()
    blink = world.hold_firmware("Pico blink")
    release = world.hold_version(blink, "1.0.0", released=True)
    kept = world.units.hold()
    retired = world.units.hold(revision_id=world.directory.hold().revision_id)
    gone = world.units.hold()
    for unit in (kept, retired, gone):
        world.hold_flash(unit, release)
    world.units.held[retired.unit_id] = replace(retired, retired=True, revision_id=None)
    del world.units.held[gone.unit_id]

    boards = await world.list_boards(BENCH, blink.id)

    assert [board.unit for board in boards] == [kept]
    assert world.directory.asked == []


async def test_a_firmware_on_no_board_lists_none_and_asks_nothing_more() -> None:
    world = World()
    blink = world.hold_firmware("Pico blink")
    world.hold_version(blink, "1.0.0", released=True)

    assert await world.list_boards(BENCH, blink.id) == []
    assert world.directory.asked == []


async def test_a_firmware_not_in_the_workspace_is_not_found() -> None:
    # Requirement 4.3: another bench's id reads the same, the fakes holding one bench.
    world = World()

    with pytest.raises(FirmwareNotFoundError, match="that firmware doesn't exist"):
        await world.list_boards(BENCH, FirmwareId(uuid7()))


# --- Property 5: the boards are the units the firmware runs on now --------------------------

# Small pools, so flashes often share a time, a logging time or both, and the id decides.
_TIMES = st.sampled_from([NOW - timedelta(days=2), NOW - timedelta(days=1), NOW])
# Each unit: its code's number, whether it is retired, gone, and held by a revision.
_UNITS = st.lists(
    st.tuples(st.integers(1, 9999), st.booleans(), st.booleans(), st.booleans()),
    min_size=1,
    max_size=4,
    unique_by=lambda unit: unit[0],
)
# Each flash: which unit, which of the four versions, when it was flashed and logged.
_FLASHES = st.lists(st.tuples(st.integers(0, 3), st.integers(0, 3), _TIMES, _TIMES), max_size=8)


def _when(flash: Flash) -> tuple[datetime, datetime, UUID]:
    """Decision 4's order, spelled out rather than read from `Flash.order`."""
    return (flash.flashed_at, flash.created_at, flash.id)


@given(units=_UNITS, flashes=_FLASHES)
def test_the_boards_are_the_units_the_firmware_runs_on_now(
    units: list[tuple[int, bool, bool, bool]],
    flashes: list[tuple[int, int, datetime, datetime]],
) -> None:
    """Property 5: the boards are the units the firmware runs on now.

    For any flashes and units, a firmware's boards are exactly the units, neither retired nor
    gone, whose current flash names one of its versions, each once, ordered by code: each with
    that flash, the revision holding it now, and the firmware's newer release when its version
    is below the latest. Two firmware share the bench, so a board that moved on to the other is
    left out, and the units are held in an order their codes don't follow.

    **Validates: Requirements 4.1, 4.2**
    """

    async def scenario() -> None:
        world = World()
        blink = world.hold_firmware("Pico blink")
        station = world.hold_firmware("Weather station")
        versions = [
            world.hold_version(blink, "1.0.0", released=True),
            world.hold_version(blink, "1.1.0", released=True),
            world.hold_version(station, "1.0.0", released=True),
            world.hold_version(station, "2.0.0", released=True),
        ]
        revision = world.directory.hold("Greenhouse controller", "A")
        held = [
            world.units.hold(
                f"WX-U-{number:04}",
                retired=retired,
                # Inventory holds a unit for a build only while it is reserved or in use.
                revision_id=revision.revision_id if reserved and not retired else None,
            )
            for number, retired, _, reserved in units
        ]
        recorded = [
            world.hold_flash(
                held[which % len(held)], versions[version], flashed_at=at, logged_at=logged
            )
            for which, version, at, logged in flashes
        ]
        gone = {held[index].unit_id for index, unit in enumerate(units) if unit[2]}
        for unit_id in gone:
            del world.units.held[unit_id]

        boards = await world.list_boards(BENCH, blink.id)

        newest: dict[UnitId, Flash] = {}
        for flash in recorded:
            if flash.unit_id not in newest or _when(flash) > _when(newest[flash.unit_id]):
                newest[flash.unit_id] = flash
        blinks = {versions[0].id, versions[1].id}
        expected = sorted(
            (
                unit
                for unit in held
                if not unit.retired
                and unit.unit_id not in gone
                and unit.unit_id in newest
                and newest[unit.unit_id].version_id in blinks
            ),
            key=lambda unit: unit.code.value,
        )
        assert [board.unit for board in boards] == expected
        assert [board.current.entry.flash for board in boards] == [
            newest[unit.unit_id] for unit in expected
        ]
        for board in boards:
            on_first = board.current.entry.flash.version_id == versions[0].id
            assert board.newer_release == (versions[1] if on_first else None)
            assert board.revision == (revision if board.unit.revision_id is not None else None)

    anyio.run(scenario)
