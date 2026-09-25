"""The pinout use cases over the in-memory catalog.

The bench is the one every catalog test runs on, *Passives → Resistors*, with one part in it:
a pinout is always some part's, and which part it is makes no difference to these rules.
"""

from datetime import timedelta
from uuid import uuid7

import pytest
from hypothesis import HealthCheck, given, settings

from support.catalog import BENCH, NOW, World
from support.pinouts import pinouts, rows_of
from wiredex.catalog.domain.errors import InvalidPinoutError, PartNotFoundError
from wiredex.catalog.domain.part import PartDefinition
from wiredex.catalog.domain.pinout import Pinout, RawPin
from wiredex.catalog.domain.values import PartDefinitionId

pytestmark = pytest.mark.anyio

# Four of the BME280's eight pins, spelled as design.md's demo bench spells them: one pin
# carrying alternate functions, two at 3V3, and numbers that skip, because a table is read in
# its own order and not sorted.
BME280_ROWS = (
    RawPin(number="1", label="GND", type="ground"),
    RawPin(number="3", label="SDI", type="io", functions=("SDA", "MOSI"), voltage="3V3"),
    RawPin(number="4", label="SCK", type="io", functions=("SCL",), voltage="3V3"),
    RawPin(number="8", label="VDD", type="power"),
)


def a_sensor(world: World) -> PartDefinition:
    """A part with no pins yet, written straight to the store: nothing here defines parts."""
    return world.add_part(world.resistors, "BME280")


async def test_a_saved_pinout_reads_back_whole_and_in_order() -> None:
    # Requirements 1.1 and 1.3: the table is stored as one thing and read as it was typed.
    world = World()
    part = a_sensor(world)

    saved = await world.replace_pinout(BENCH, part.id, BME280_ROWS)
    read = await world.get_pinout(BENCH, part.id)

    assert read == saved
    assert [str(pin.number) for pin in read] == ["1", "3", "4", "8"]
    sdi = list(read)[1]
    assert [str(function) for function in sdi.functions] == ["SDA", "MOSI"]
    assert str(sdi.voltage) == "3.3"
    assert world.catalog.commits == 1
    assert world.catalog.opened_for == [BENCH, BENCH]


async def test_a_part_with_no_pins_has_an_empty_pinout_not_a_missing_one() -> None:
    # Requirement 1.2: most parts never get a pin table, and reading one isn't an error.
    world = World()
    part = a_sensor(world)

    assert await world.get_pinout(BENCH, part.id) == Pinout.empty()
    assert world.catalog.commits == 0


async def test_saving_the_same_table_again_commits_nothing() -> None:
    # Requirement 1.6: a resubmitted form is answered, not written.
    world = World()
    part = a_sensor(world)
    await world.replace_pinout(BENCH, part.id, BME280_ROWS)
    committed = world.catalog.commits
    world.clock.advance(timedelta(hours=1))

    again = await world.replace_pinout(BENCH, part.id, BME280_ROWS)

    assert world.catalog.commits == committed
    assert again == await world.get_pinout(BENCH, part.id)
    assert part.updated_at == NOW


async def test_the_same_table_spelled_another_way_is_still_the_same_table() -> None:
    # What the editor sends back is what it was shown: the stored 3.3 where 3V3 was typed, and
    # a ball in whichever case. Both normalize, so neither is a change (requirement 1.6).
    world = World()
    part = a_sensor(world)
    await world.replace_pinout(
        BENCH, part.id, [RawPin(number="a1", label="VDD", type="power", voltage="3V3")]
    )
    committed = world.catalog.commits

    await world.replace_pinout(
        BENCH, part.id, [RawPin(number="A1", label="VDD", type="power", voltage="3.3")]
    )

    assert world.catalog.commits == committed


async def test_saving_a_pinout_marks_the_part_updated() -> None:
    # Requirement 1.5: the pins are part of what the part is, so the part moves with them.
    world = World()
    part = a_sensor(world)
    world.clock.advance(timedelta(days=1))

    await world.replace_pinout(BENCH, part.id, BME280_ROWS)

    assert part.updated_at == world.clock.now()
    assert part.updated_at > part.created_at
    assert world.catalog.commits == 1


async def test_saving_no_pins_clears_the_pinout() -> None:
    # Requirement 1.4: emptying the table is how a pinout entered by mistake is taken back.
    world = World()
    part = a_sensor(world)
    await world.replace_pinout(BENCH, part.id, BME280_ROWS)
    world.clock.advance(timedelta(minutes=5))

    cleared = await world.replace_pinout(BENCH, part.id, [])

    assert len(cleared) == 0
    assert await world.get_pinout(BENCH, part.id) == Pinout.empty()
    # Clearing is a change like any other, so it marks the part too (requirement 1.5).
    assert part.updated_at == world.clock.now()
    assert world.catalog.commits == 2


async def test_a_refused_table_leaves_the_stored_one_untouched() -> None:
    # Requirement 1.3: whole or not at all, so forty good rows and one bad one save nothing.
    world = World()
    part = a_sensor(world)
    await world.replace_pinout(BENCH, part.id, BME280_ROWS)
    committed = world.catalog.commits

    with pytest.raises(InvalidPinoutError) as refused:
        await world.replace_pinout(
            BENCH, part.id, [*BME280_ROWS, RawPin(number="1", label="GND", type="ground")]
        )

    assert refused.value.row == 5
    assert world.catalog.commits == committed
    assert len(await world.get_pinout(BENCH, part.id)) == 4


async def test_the_pinout_of_a_part_that_is_not_in_the_bench_is_simply_not_found() -> None:
    """Requirement 1.9: another workspace's part reads as no part at all.

    The fakes hold one bench's rows, as a real unit of work sees one workspace's, so a part
    of another workspace is a part that isn't there — which is the answer either way.
    """
    world = World()
    elsewhere = PartDefinitionId(uuid7())

    with pytest.raises(PartNotFoundError):
        await world.get_pinout(BENCH, elsewhere)
    with pytest.raises(PartNotFoundError):
        await world.replace_pinout(BENCH, elsewhere, BME280_ROWS)

    assert world.catalog.pinouts.saved == {}
    assert world.catalog.commits == 0


async def test_deleting_a_part_takes_its_pins_with_it() -> None:
    # Requirement 1.7: the database cascades, and the fakes do the same, so no use case has
    # to remember to delete pins and none is left able to read orphaned ones.
    world = World()
    part = a_sensor(world)
    await world.replace_pinout(BENCH, part.id, BME280_ROWS)

    await world.delete_part(BENCH, part.id)

    assert world.catalog.pinouts.saved == {}
    with pytest.raises(PartNotFoundError):
        await world.get_pinout(BENCH, part.id)


# --- Property (design.md's correctness property 5) ----------------------------


# The only function-scoped fixture in reach is `anyio_backend`, which names the event loop
# and carries no state; each example builds its own World, so nothing crosses between them.
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(first=pinouts(), second=pinouts())
async def test_replacing_a_pinout_is_total(first: Pinout, second: Pinout) -> None:
    """Property 5: a replace leaves exactly the new table, and saving it again commits nothing.

    **Validates: Requirements 1.3, 1.4, 1.6**
    """
    world = World()
    part = a_sensor(world)
    await world.replace_pinout(BENCH, part.id, rows_of(first))

    await world.replace_pinout(BENCH, part.id, rows_of(second))
    read = await world.get_pinout(BENCH, part.id)

    # Equality is pins and order, so nothing of the first table can have survived the second.
    assert read == second
    assert list(read) == list(second)
    committed = world.catalog.commits
    await world.replace_pinout(BENCH, part.id, rows_of(second))
    assert world.catalog.commits == committed
