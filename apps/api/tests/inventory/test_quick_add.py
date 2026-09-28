"""Quick-add over the in-memory intake: a part and its first stock in one unit of work.

The catalog's half is `FakePartCatalog`, which answers in inventory's words what catalog's
`PartDrafts` would. So these tests pin what inventory does with its answers: define the part
and receive its stock, a lot or units, committed once; or refuse with every problem at once,
or with the 409 naming the part that holds the number, and write nothing.
"""

from collections.abc import Callable
from uuid import uuid7

import pytest

from support.inventory import BENCH, World
from wiredex.inventory.application.intake import QuickAddition, QuickStock
from wiredex.inventory.domain.errors import (
    IntakeRefusedError,
    PartAlreadyDefinedError,
    PartNotFoundError,
)
from wiredex.inventory.domain.intake import (
    MAX_LOT_QUANTITY,
    MAX_UNITS_PER_RECEIPT,
    PartDraft,
    ProblemCode,
)
from wiredex.inventory.domain.values import LocationId, MovementKind, PartId

pytestmark = pytest.mark.anyio


def a_resistor(world: World, mpn: str | None = None) -> PartDraft:
    return PartDraft(category_id=world.resistors.id, name="10k 0805", manufacturer="Yageo", mpn=mpn)


def a_board(world: World) -> PartDraft:
    return PartDraft(category_id=world.boards.id, name="ESP32-C3 SuperMini")


def nowhere() -> LocationId:
    """A location this bench doesn't hold, as another workspace's is to it."""
    return LocationId(uuid7())


class TestAdding:
    async def test_a_part_alone_is_defined_with_no_stock(self) -> None:
        world = World()
        draft = a_resistor(world)

        added = await world.quick_add(BENCH, QuickAddition(draft))

        assert added.part.name == "10k 0805"
        assert added.part.tracked_individually is False
        assert (added.balance, added.units) == (None, ())
        assert world.inventory.catalog.defined == [draft]
        assert world.inventory.lots.saved == {}
        assert world.inventory.ledger.saved == []
        assert world.inventory.commits == 1

    async def test_a_lot_counted_part_gets_one_receive_and_answers_its_balance(self) -> None:
        world = World()

        added = await world.quick_add(
            BENCH, QuickAddition(a_resistor(world), QuickStock(world.drawer.id, 200))
        )

        lot = await world.inventory.lots.for_part_at(added.part.id, world.drawer.id)
        assert lot is not None
        assert added.balance is not None
        assert (added.balance.lot_id, int(added.balance.on_hand)) == (lot.id, 200)
        assert await world.inventory.balances.get(lot.id) == added.balance
        movements = await world.inventory.ledger.movements_of(lot.id)
        assert [(m.kind, m.change) for m in movements] == [(MovementKind.RECEIVE, 200)]
        assert added.units == ()
        assert world.inventory.units.saved == {}

    async def test_a_unit_tracked_part_gets_that_many_blank_units_with_their_codes(self) -> None:
        world = World()

        added = await world.quick_add(
            BENCH, QuickAddition(a_board(world), QuickStock(world.drawer.id, 3))
        )

        assert [str(unit.code) for unit in added.units] == ["WX-U-0001", "WX-U-0002", "WX-U-0003"]
        assert all(unit.serial is None and unit.mac is None for unit in added.units)
        assert {unit.part_id for unit in added.units} == {added.part.id}
        lot = await world.inventory.lots.for_part_at(added.part.id, world.drawer.id)
        assert lot is not None
        assert {unit.lot_id for unit in added.units} == {lot.id}
        movements = await world.inventory.ledger.movements_of(lot.id)
        assert [(m.kind, m.change) for m in movements] == [(MovementKind.RECEIVE, 3)]
        assert await world.inventory.units.in_stock_at(lot.id) == 3
        assert added.balance is None

    async def test_the_part_and_its_stock_are_one_unit_of_work_committed_once(self) -> None:
        world = World()

        await world.quick_add(BENCH, QuickAddition(a_board(world), QuickStock(world.drawer.id, 2)))

        assert world.inventory.opened_for == [BENCH]
        assert world.inventory.commits == 1

    async def test_a_duplicate_hands_its_source_to_the_catalog(self) -> None:
        world = World()
        source = world.inventory.catalog.hold_part(
            "10k 0805", world.resistors, manufacturer="Yageo", mpn="RC0805FR-0710KL"
        )

        added = await world.quick_add(
            BENCH,
            QuickAddition(a_resistor(world, mpn="RC0805FR-074K7L"), pinout_from=source.id),
        )

        assert world.inventory.catalog.pinout_sources == [source.id]
        assert added.part.id != source.id


class TestRefusing:
    async def test_every_problem_is_refused_at_once_each_on_its_field(self) -> None:
        world = World()
        sensors = world.inventory.catalog.add_category("Sensors", required=["i2c_address"])
        draft = PartDraft(category_id=sensors.id, manufacturer="Bosch")

        with pytest.raises(IntakeRefusedError) as refused:
            await world.quick_add(BENCH, QuickAddition(draft, QuickStock(nowhere(), 0)))

        found = [(problem.row, problem.column, problem.code) for problem in refused.value.problems]
        assert found == [
            (None, "name", ProblemCode.MISSING),
            (None, "i2c_address", ProblemCode.MISSING),
            (None, "location", ProblemCode.UNKNOWN_LOCATION),
            (None, "quantity", ProblemCode.BAD_QUANTITY),
        ]
        assert str(refused.value) == "the part can't be added as it is"

    async def test_a_stored_part_number_is_a_409_naming_the_part(self) -> None:
        # Before any other problem: the owner opens that part instead of fixing this form.
        world = World()
        held = world.inventory.catalog.hold_part(
            "BME280 breakout", world.resistors, manufacturer="Bosch", mpn="BME280"
        )
        draft = PartDraft(
            category_id=world.resistors.id, name="Another", manufacturer=" bosch", mpn="bme280 "
        )

        with pytest.raises(PartAlreadyDefinedError) as refused:
            await world.quick_add(BENCH, QuickAddition(draft, QuickStock(nowhere(), 0)))

        assert refused.value.part == held
        assert str(refused.value) == "bme280 is already the part BME280 breakout"

    async def test_an_unknown_location_is_refused_on_the_location(self) -> None:
        world = World()

        with pytest.raises(IntakeRefusedError) as refused:
            await world.quick_add(BENCH, QuickAddition(a_resistor(world), QuickStock(nowhere(), 5)))

        found = [(problem.column, problem.code) for problem in refused.value.problems]
        assert found == [("location", ProblemCode.UNKNOWN_LOCATION)]

    async def test_while_the_category_is_unknown_only_the_shared_bounds_are_checked(
        self,
    ) -> None:
        # 101 would be too many units, but the part's kind is unknown: only its category is.
        world = World()
        draft = PartDraft(category_id=uuid7(), name="Mystery")
        stock = QuickStock(world.drawer.id, MAX_UNITS_PER_RECEIPT + 1)

        with pytest.raises(IntakeRefusedError) as refused:
            await world.quick_add(BENCH, QuickAddition(draft, stock))

        found = [(problem.column, problem.code) for problem in refused.value.problems]
        assert found == [("category", ProblemCode.UNKNOWN_CATEGORY)]


class TestConsumables:
    """09's requirements 2.5 and 2.6: a consumable is quick-added without stock, or not at all."""

    @pytest.mark.parametrize("tracked", [False, True])
    async def test_stock_for_a_consumable_is_refused_on_the_quantity(self, tracked: bool) -> None:
        # Only that problem: its location and quantity would be checked for nothing.
        world = World()
        wire = world.inventory.catalog.add_category(
            "Consumables", tracked=tracked, not_stocked=True
        )
        draft = PartDraft(category_id=wire.id, name="Hook-up wire 22 AWG")

        with pytest.raises(IntakeRefusedError) as refused:
            await world.quick_add(BENCH, QuickAddition(draft, QuickStock(nowhere(), 0)))

        found = [(problem.column, problem.code) for problem in refused.value.problems]
        assert found == [("quantity", ProblemCode.NOT_STOCKED)]
        assert world.inventory.catalog.defined == []
        assert world.inventory.commits == 0

    async def test_a_consumable_alone_is_defined_in_one_commit(self) -> None:
        world = World()
        wire = world.inventory.catalog.add_category("Consumables", not_stocked=True)
        draft = PartDraft(category_id=wire.id, name="Hook-up wire 22 AWG")

        added = await world.quick_add(BENCH, QuickAddition(draft))

        assert (added.part.not_stocked, added.balance, added.units) == (True, None, ())
        assert world.inventory.catalog.defined == [draft]
        assert world.inventory.lots.saved == {}
        assert world.inventory.commits == 1


def draft_of(world: World, *, tracked: bool) -> PartDraft:
    return a_board(world) if tracked else a_resistor(world)


@pytest.mark.parametrize(
    ("tracked", "quantity"),
    [(False, 1), (False, MAX_LOT_QUANTITY), (True, 1), (True, MAX_UNITS_PER_RECEIPT)],
)
async def test_a_quantity_within_the_bounds_of_its_kind_is_received(
    tracked: bool, quantity: int
) -> None:
    world = World()
    stock = QuickStock(world.drawer.id, quantity)

    added = await world.quick_add(BENCH, QuickAddition(draft_of(world, tracked=tracked), stock))

    lot = await world.inventory.lots.for_part_at(added.part.id, world.drawer.id)
    assert lot is not None
    balance = await world.inventory.balances.get(lot.id)
    assert balance is not None
    assert int(balance.on_hand) == quantity
    assert len(added.units) == (quantity if tracked else 0)


@pytest.mark.parametrize(
    ("tracked", "quantity", "code"),
    [
        (False, 0, ProblemCode.BAD_QUANTITY),
        (False, -3, ProblemCode.BAD_QUANTITY),
        (False, MAX_LOT_QUANTITY + 1, ProblemCode.BAD_QUANTITY),
        (True, 0, ProblemCode.BAD_QUANTITY),
        (True, MAX_UNITS_PER_RECEIPT + 1, ProblemCode.TOO_MANY_UNITS),
    ],
)
async def test_a_quantity_past_the_bounds_of_its_kind_is_refused_on_the_quantity(
    tracked: bool, quantity: int, code: ProblemCode
) -> None:
    world = World()
    stock = QuickStock(world.drawer.id, quantity)

    with pytest.raises(IntakeRefusedError) as refused:
        await world.quick_add(BENCH, QuickAddition(draft_of(world, tracked=tracked), stock))

    found = [(problem.column, problem.code) for problem in refused.value.problems]
    assert found == [("quantity", code)]


def with_problems(world: World) -> QuickAddition:
    return QuickAddition(PartDraft(category_id=world.resistors.id), QuickStock(nowhere(), 5))


def with_a_stored_part_number(world: World) -> QuickAddition:
    world.inventory.catalog.hold_part("BME280", world.resistors, mpn="BME280")
    return QuickAddition(PartDraft(category_id=world.resistors.id, name="Copy", mpn="BME280"))


def with_a_missing_pinout_source(world: World) -> QuickAddition:
    # Refused by the catalog as it defines, after the review found nothing wrong (3.4).
    stock = QuickStock(world.drawer.id, 5)
    return QuickAddition(a_resistor(world), stock, pinout_from=PartId(uuid7()))


@pytest.mark.parametrize(
    ("refusal", "error"),
    [
        (with_problems, IntakeRefusedError),
        (with_a_stored_part_number, PartAlreadyDefinedError),
        (with_a_missing_pinout_source, PartNotFoundError),
    ],
)
async def test_a_refused_quick_add_writes_nothing_and_commits_nothing(
    refusal: Callable[[World], QuickAddition], error: type[Exception]
) -> None:
    world = World()
    addition = refusal(world)
    held = dict(world.inventory.catalog.parts)

    with pytest.raises(error):
        await world.quick_add(BENCH, addition)

    assert world.inventory.catalog.defined == []
    assert world.inventory.catalog.parts == held
    assert world.inventory.lots.saved == {}
    assert world.inventory.ledger.saved == []
    assert world.inventory.balances.saved == {}
    assert world.inventory.units.saved == {}
    assert world.inventory.commits == 0
