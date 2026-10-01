"""Inventory's share of the trash over the in-memory inventory (16-soft-delete-and-trash).

Moving a unit to the trash is `DeleteUnit`, whose refusals `test_unit_use_cases.py` covers; here is
what follows it: the trash's page, restoring, deleting for good and emptying, and what a unit in
the trash still holds (its serial and its MAC).
"""

from datetime import timedelta
from uuid import uuid7

import pytest

from support.inventory import BENCH, UNIT_TRACKED_PART, World
from wiredex.inventory.application.trash import (
    DeleteUnitForGood,
    EmptyUnitTrash,
    ListTrashedUnits,
    RestoreUnit,
)
from wiredex.inventory.domain.errors import (
    DuplicateMacError,
    DuplicateSerialError,
    UnitNotFoundError,
)
from wiredex.inventory.domain.unit import Unit, UnitStatus
from wiredex.inventory.domain.values import Mac, MovementKind, Serial, UnitId
from wiredex.shared_kernel.domain.trash import TrashPosition

pytestmark = pytest.mark.anyio


async def a_trashed_unit(world: World, serial: str | None = None) -> Unit:
    """A retired unit of a fresh lot, moved to the trash a minute after the last one."""
    lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=0)
    unit = world.hold_unit(
        UNIT_TRACKED_PART,
        lot,
        status=UnitStatus.RETIRED,
        serial=None if serial is None else Serial(serial),
    )
    world.clock.advance(timedelta(minutes=1))
    await world.delete_unit(BENCH, unit.id)
    return unit


async def test_the_trash_lists_its_units_newest_first_from_a_position() -> None:
    world = World()
    first, second, third = [await a_trashed_unit(world) for _ in range(3)]
    listed = ListTrashedUnits(world.inventory.for_workspace)

    assert await listed(BENCH, None, 2) == [third, second]
    assert second.trashed_at is not None
    assert await listed(BENCH, TrashPosition(second.trashed_at, second.id), 2) == [first]


async def test_a_restored_unit_is_back_retired_as_it_was() -> None:
    world = World()
    unit = await a_trashed_unit(world)

    await RestoreUnit(world.inventory.for_workspace)(BENCH, unit.id)

    restored = await world.get_unit(BENCH, unit.id)
    assert restored.status is UnitStatus.RETIRED
    assert not restored.in_trash
    assert [found.id for found in await world.list_units_of_part(BENCH, UNIT_TRACKED_PART)] == [
        unit.id
    ]


async def test_only_a_unit_in_the_trash_is_restored_or_deleted_for_good() -> None:
    # Requirements 5.3 and 6.2: a live unit and an unknown one are both not in the trash.
    world = World()
    lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=1)
    live = world.hold_unit(UNIT_TRACKED_PART, lot)
    work = world.inventory.for_workspace

    for missing in (live.id, UnitId(uuid7())):
        with pytest.raises(UnitNotFoundError, match="isn't in the trash"):
            await RestoreUnit(work)(BENCH, missing)
        with pytest.raises(UnitNotFoundError, match="isn't in the trash"):
            await DeleteUnitForGood(work)(BENCH, missing)

    assert live.id in world.inventory.units.saved
    assert world.inventory.commits == 0


async def test_a_unit_deleted_for_good_leaves_its_movements() -> None:
    # Requirement 6.3, as deleting a unit did before.
    world = World()
    lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=1)
    unit = world.hold_unit(UNIT_TRACKED_PART, lot)
    await world.retire_unit(BENCH, unit.id)
    await world.delete_unit(BENCH, unit.id)

    await DeleteUnitForGood(world.inventory.for_workspace)(BENCH, unit.id)

    assert unit.id not in world.inventory.units.saved
    movements = await world.inventory.ledger.movements_of(lot.id)
    assert [movement.kind for movement in movements] == [MovementKind.ADJUST]


async def test_emptying_the_trash_deletes_only_what_is_in_it() -> None:
    world = World()
    trashed = [await a_trashed_unit(world) for _ in range(2)]
    lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=1)
    live = world.hold_unit(UNIT_TRACKED_PART, lot)

    emptied = await EmptyUnitTrash(world.inventory.for_workspace)(BENCH)

    assert emptied == len(trashed)
    assert list(world.inventory.units.saved) == [live.id]


async def test_a_unit_in_the_trash_keeps_its_serial_and_mac() -> None:
    # Requirement 3.4: refused as for any taken serial or MAC.
    world = World()
    lot = world.hold_lot(UNIT_TRACKED_PART, world.drawer, on_hand=1)
    gone = world.hold_unit(
        UNIT_TRACKED_PART, lot, status=UnitStatus.RETIRED, mac=Mac("aa:bb:cc:dd:ee:ff")
    )
    gone.serial = Serial("SN-1")
    await world.delete_unit(BENCH, gone.id)
    live = world.hold_unit(UNIT_TRACKED_PART, lot)

    with pytest.raises(DuplicateSerialError):
        await world.relabel_unit(BENCH, live.id, Serial("sn-1"), None)
    with pytest.raises(DuplicateMacError):
        await world.relabel_unit(BENCH, live.id, None, Mac("AA:BB:CC:DD:EE:FF"))
