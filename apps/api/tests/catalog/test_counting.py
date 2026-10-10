"""A part doesn't change between counted in lots and tracked as units while it holds stock of
the kind it would stop being: that stock would be left where no operation reaches it.

Three writes change a part's kind, and each is refused with the parts in the way: a category's
"tracked individually" flag, a category moved under another answer, and a part filed under a
category that counts the other way.
"""

import pytest

from support.catalog import BENCH, World
from wiredex.catalog.application.parts import PartRevision
from wiredex.catalog.application.ports import StockCounted
from wiredex.catalog.domain.errors import MiscountedStockError
from wiredex.catalog.domain.part import PartDetails

pytestmark = pytest.mark.anyio

LOOSE = StockCounted(loose=12)
UNITS = StockCounted(units=2)


async def test_a_category_isnt_tracked_while_its_parts_hold_loose_stock() -> None:
    world = World()
    resistor = world.add_part(world.resistors, "R 4k7 0805")
    world.add_part(world.resistors, "R 10k 0805")
    world.part_stock.kinds[resistor.id] = LOOSE

    # Set on the parent: Resistors inherits it, so its parts would turn too.
    with pytest.raises(
        MiscountedStockError,
        match="R 4k7 0805 would be tracked as units while holding stock counted loose",
    ):
        await world.set_category_tracking(BENCH, world.passives.id, True)

    assert world.passives.tracked_individually is None
    assert world.catalog.commits == 0

    # At zero, the same change goes through.
    world.part_stock.kinds.clear()
    view = await world.set_category_tracking(BENCH, world.passives.id, True)
    assert view.flags.tracked_individually is True


async def test_a_category_isnt_counted_in_lots_while_its_parts_have_units() -> None:
    world = World()
    await world.set_category_tracking(BENCH, world.resistors.id, True)
    board = world.add_part(world.resistors, "ESP32 DevKit")
    world.part_stock.kinds[board.id] = UNITS

    for untracked in (False, None):
        with pytest.raises(
            MiscountedStockError,
            match="ESP32 DevKit would be counted in lots while having units: retire or delete",
        ):
            await world.set_category_tracking(BENCH, world.resistors.id, untracked)

    assert world.resistors.tracked_individually is True
    # Loose stock is no obstacle to staying tracked, nor units to a flag that changes nothing.
    await world.set_category_tracking(BENCH, world.resistors.id, True)


async def test_a_flag_that_turns_no_part_asks_nothing_of_inventory() -> None:
    world = World()
    world.add_part(world.resistors)
    await world.set_category_tracking(BENCH, world.resistors.id, False)
    # Passives set to what Resistors already answers on its own: no part of Passives turns.
    world.passives.tracked_individually = True
    await world.set_category_tracking(BENCH, world.resistors.id, False)

    assert world.part_stock.asked_kinds == []


async def test_a_refusal_names_three_parts_and_counts_the_rest() -> None:
    world = World()
    for name in ("R 1k", "R 2k", "R 3k", "R 4k", "R 5k"):
        world.part_stock.kinds[world.add_part(world.resistors, name).id] = LOOSE

    with pytest.raises(MiscountedStockError, match=r"^R 1k, R 2k, R 3k and 2 more would be"):
        await world.set_category_tracking(BENCH, world.resistors.id, True)


async def test_a_category_isnt_moved_under_another_answer_while_its_parts_hold_stock() -> None:
    world = World()
    boards = world.add_category("Boards")
    await world.set_category_tracking(BENCH, boards.id, True)
    resistor = world.add_part(world.resistors)
    world.part_stock.kinds[resistor.id] = LOOSE

    with pytest.raises(MiscountedStockError, match="would be tracked as units"):
        await world.move_category(BENCH, world.passives.id, boards.id)
    assert world.passives.parent_id is None

    # A category that answers for itself keeps its answer wherever it sits.
    await world.set_category_tracking(BENCH, world.resistors.id, False)
    await world.move_category(BENCH, world.passives.id, boards.id)
    assert world.passives.parent_id == boards.id


async def test_a_part_isnt_filed_under_a_category_that_counts_the_other_way() -> None:
    world = World()
    boards = world.add_category("Boards")
    await world.set_category_tracking(BENCH, boards.id, True)
    part = world.add_part(world.passives, "Breakout")
    revision = PartRevision(PartDetails(part.name), {}, category_id=boards.id)

    world.part_stock.kinds[part.id] = LOOSE
    with pytest.raises(MiscountedStockError, match="Breakout would be tracked as units"):
        await world.update_part(BENCH, part.id, revision)
    assert part.category_id == world.passives.id

    # With none, it moves; and back again is refused while it has units.
    world.part_stock.kinds.clear()
    await world.update_part(BENCH, part.id, revision)
    assert part.category_id == boards.id
    world.part_stock.kinds[part.id] = UNITS
    with pytest.raises(MiscountedStockError, match="Breakout would be counted in lots"):
        await world.update_part(
            BENCH, part.id, PartRevision(PartDetails(part.name), {}, category_id=world.passives.id)
        )
    # An edit that keeps its category asks nothing.
    asked = len(world.part_stock.asked_kinds)
    await world.update_part(BENCH, part.id, PartRevision(PartDetails(part.name), {}))
    assert len(world.part_stock.asked_kinds) == asked
