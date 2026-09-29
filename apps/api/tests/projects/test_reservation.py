"""The reservation choice and the named-unit checks (task 10, properties 4 and 5).

`Reservation.choose` and `check_named_units` are pure functions of the stock a reserve locked.
The generators below build a `ReservableStock` that always covers the needs they draw beside
it, so `choose` meets only stock it can satisfy, as the use case guarantees by running the
checks and the shortage report first.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid7

import pytest
from hypothesis import given
from hypothesis import strategies as st

from wiredex.projects.domain.lifecycle import (
    RepeatedUnitError,
    TooManyUnitsError,
    Transition,
    UnitNotInStockError,
    UnitNotNeededError,
    UnknownUnitError,
    _NamedUnitError,
)
from wiredex.projects.domain.reservation import (
    LotPick,
    ReservableLot,
    ReservableStock,
    Reservation,
    StockUnit,
    check_named_units,
)
from wiredex.projects.domain.shortage import PartFacts
from wiredex.projects.domain.values import LotId, PartId, UnitId

NOW = datetime(2026, 9, 28, 10, 0, tzinfo=UTC)

# What a named-unit check catches: the refusal's class and the unit it names, or None.
_Failure = tuple[type[_NamedUnitError], UnitId] | None


def facts_of(
    part_id: PartId, name: str = "Resistor 10k", *, not_stocked: bool = False
) -> PartFacts:
    return PartFacts(part_id, name, None, None, None, False, not_stocked)


def a_lot(part_id: PartId, code: str, available: int) -> ReservableLot:
    return ReservableLot(LotId(uuid7()), part_id, code, available)


def a_unit(part_id: PartId, lot_id: LotId, code: str, *, in_stock: bool = True) -> StockUnit:
    return StockUnit(UnitId(uuid7()), code, part_id, lot_id, in_stock)


def stock_of(
    lots: Sequence[ReservableLot],
    units: Sequence[StockUnit] = (),
    named: Sequence[StockUnit] = (),
    *,
    changed: bool = False,
) -> ReservableStock:
    """A `ReservableStock` with its lots in lot-id order and its units in id order, as the
    lock reads them."""
    return ReservableStock(
        lots=tuple(sorted(lots, key=lambda lot: lot.lot_id)),
        units=tuple(sorted(units, key=lambda unit: unit.unit_id)),
        named={unit.unit_id: unit for unit in named},
        now=NOW,
        changed=changed,
    )


@dataclass(frozen=True)
class Scenario:
    """A property-4 case: stocked needs, stock that covers them, and a valid named list."""

    needs: Mapping[PartId, int]
    stock: ReservableStock
    named: list[UnitId]


@dataclass(frozen=True)
class NamedCheck:
    """A property-5 case: needs, facts, stock and a named list that may or may not be valid."""

    needs: Mapping[PartId, int]
    facts: Mapping[PartId, PartFacts]
    named: list[UnitId]
    stock: ReservableStock


# --- ReservableStock.free -------------------------------------------------------------------


def test_free_sums_a_parts_available_over_its_lots() -> None:
    resistor, capacitor = PartId(uuid7()), PartId(uuid7())
    stock = stock_of(
        [
            a_lot(resistor, "WX-L-0001", 40),
            a_lot(resistor, "WX-L-0002", 10),
            a_lot(capacitor, "WX-L-0003", 5),
        ]
    )

    assert stock.free() == {resistor: 50, capacitor: 5}


# --- Reservation.choose, worked examples ----------------------------------------------------


def test_the_largest_lot_goes_first_then_by_location_code() -> None:
    # A need spread over three lots: most available first, then the smaller, none touched once
    # the need is met; ties by location code.
    part = PartId(uuid7())
    big = a_lot(part, "WX-L-0009", 30)
    small = a_lot(part, "WX-L-0002", 5)
    empty = a_lot(part, "WX-L-0001", 0)
    stock = stock_of([small, big, empty])

    reservation = Reservation.choose({part: 32}, stock, named=[])

    assert reservation.picks == (
        LotPick(big.lot_id, 30, ()),
        LotPick(small.lot_id, 2, ()),
    )


def test_ties_on_available_break_by_location_code() -> None:
    part = PartId(uuid7())
    later = a_lot(part, "WX-L-0007", 10)
    earlier = a_lot(part, "WX-L-0003", 10)
    stock = stock_of([later, earlier])

    reservation = Reservation.choose({part: 4}, stock, named=[])

    assert reservation.picks == (LotPick(earlier.lot_id, 4, ()),)


def test_a_lot_of_units_takes_them_in_code_order_one_per_piece() -> None:
    part = PartId(uuid7())
    lot = a_lot(part, "WX-L-0001", 3)
    u3 = a_unit(part, lot.lot_id, "WX-U-0003")
    u1 = a_unit(part, lot.lot_id, "WX-U-0001")
    u2 = a_unit(part, lot.lot_id, "WX-U-0002")
    stock = stock_of([lot], units=[u3, u1, u2])

    reservation = Reservation.choose({part: 2}, stock, named=[])

    # Two pieces, its two lowest-coded units, in code order, before any loose piece.
    (pick,) = reservation.picks
    assert pick.lot_id == lot.lot_id
    assert pick.quantity == 2
    assert pick.unit_ids == (u1.unit_id, u2.unit_id)


def test_loose_pieces_follow_the_units_a_lot_has() -> None:
    part = PartId(uuid7())
    lot = a_lot(part, "WX-L-0001", 5)  # two units, three loose
    u1 = a_unit(part, lot.lot_id, "WX-U-0001")
    u2 = a_unit(part, lot.lot_id, "WX-U-0002")
    stock = stock_of([lot], units=[u1, u2])

    reservation = Reservation.choose({part: 4}, stock, named=[])

    (pick,) = reservation.picks
    assert pick.quantity == 4
    # Both units, then loose pieces: unit ids only for the pieces a unit covers.
    assert pick.unit_ids == (u1.unit_id, u2.unit_id)


def test_a_named_unit_comes_from_its_own_lot_first() -> None:
    part = PartId(uuid7())
    drawer = a_lot(part, "WX-L-0001", 10)  # the biggest, but not the named unit's
    box = a_lot(part, "WX-L-0005", 3)
    named = a_unit(part, box.lot_id, "WX-U-0004")
    stock = stock_of([drawer, box], units=[named], named=[named])

    reservation = Reservation.choose({part: 3}, stock, named=[named.unit_id])

    picks = {pick.lot_id: pick for pick in reservation.picks}
    # One piece from the named unit's lot, its unit; the rest from the biggest lot.
    assert picks[box.lot_id].unit_ids == (named.unit_id,)
    assert picks[box.lot_id].quantity == 1
    assert picks[drawer.lot_id].quantity == 2


def test_a_consumable_is_never_taken() -> None:
    resistor = PartId(uuid7())
    lot = a_lot(resistor, "WX-L-0001", 5)
    # A consumable has no stocked need, so `needs` never carries it; no lot of it is locked.
    stock = stock_of([lot])

    reservation = Reservation.choose({resistor: 2}, stock, named=[])

    assert [pick.lot_id for pick in reservation.picks] == [lot.lot_id]


# --- Reservation.choose, the demo's greenhouse -----------------------------------------------


def test_the_demo_greenhouse_choice() -> None:
    """Decision 9: reserving *Greenhouse controller* `A` with no named units takes the bench's
    one ESP32 board, three 10k from Drawer 3 and one 100n from the Parts box."""
    esp32, resistor, capacitor = PartId(uuid7()), PartId(uuid7()), PartId(uuid7())
    board_lot = a_lot(esp32, "WX-L-0004", 1)  # Parts box, one board
    board = a_unit(esp32, board_lot.lot_id, "WX-U-0001")
    drawer = a_lot(resistor, "WX-L-0003", 40)  # Drawer 3
    parts_box = a_lot(capacitor, "WX-L-0004", 20)
    stock = stock_of([board_lot, drawer, parts_box], units=[board])

    reservation = Reservation.choose({esp32: 1, resistor: 3, capacitor: 1}, stock, named=[])

    picks = {pick.lot_id: pick for pick in reservation.picks}
    assert picks[board_lot.lot_id] == LotPick(board_lot.lot_id, 1, (board.unit_id,))
    assert picks[drawer.lot_id] == LotPick(drawer.lot_id, 3, ())
    assert picks[parts_box.lot_id] == LotPick(parts_box.lot_id, 1, ())
    # A pure function: the same stock always gets the same choice (the demo relies on it).
    assert Reservation.choose({esp32: 1, resistor: 3, capacitor: 1}, stock, named=[]) == reservation


# --- Property 4 ------------------------------------------------------------------------------


@st.composite
def _part_stock(
    draw: st.DrawFn, part: PartId, start_code: int
) -> tuple[list[ReservableLot], list[StockUnit], int]:
    """One part's lots, some unit-tracked (one in-stock unit per piece), and the next code."""
    lots: list[ReservableLot] = []
    units: list[StockUnit] = []
    code = start_code
    for _ in range(draw(st.integers(1, 3))):
        available = draw(st.integers(0, 8))
        lot = a_lot(part, f"WX-L-{draw(st.integers(1, 40)):04d}", available)
        lots.append(lot)
        if draw(st.booleans()):  # a unit-tracked lot: one unit per piece
            for _ in range(available):
                units.append(a_unit(part, lot.lot_id, f"WX-U-{code:04d}"))
                code += 1
    return lots, units, code


@st.composite
def scenarios(draw: st.DrawFn) -> Scenario:
    """Stocked needs, a `ReservableStock` that covers them, and a valid list of named units.

    A handful of parts, each with one to three lots of a drawn availability; some lots are
    unit-tracked, holding one in-stock unit per piece with an ordered code. A part's need is
    drawn between one and its free stock, so the stock always covers it; named units are drawn
    from the part's in-stock units, at most its need.
    """
    parts = [PartId(uuid7()) for _ in range(draw(st.integers(1, 3)))]
    lots: list[ReservableLot] = []
    units: list[StockUnit] = []
    needs: dict[PartId, int] = {}
    code = 1

    for part in parts:
        part_lots, part_units, code = draw(_part_stock(part, code))
        lots.extend(part_lots)
        units.extend(part_units)
        free = sum(lot.available for lot in part_lots)
        if free:  # only a part with free stock carries a need
            needs[part] = draw(st.integers(1, free))

    # Name some of a part's in-stock units, at most its need, so the list is always valid.
    named: list[UnitId] = []
    for part, need in needs.items():
        part_units = [unit for unit in units if unit.part_id == part]
        picked = draw(st.integers(0, min(need, len(part_units))))
        named.extend(unit.unit_id for unit in draw(st.permutations(part_units))[:picked])
    named_set = set(named)
    stock = stock_of(lots, units=units, named=[u for u in units if u.unit_id in named_set])
    return Scenario(needs, stock, named)


@given(scenario=scenarios())
def test_property_4_a_reservation_takes_exactly_the_need(scenario: Scenario) -> None:
    """Property 4: a reservation takes exactly the need, units first, and with no named units
    from the fewest lots.

    For any stocked needs, any locked stock that covers them and any named units
    `check_named_units` accepts, `Reservation.choose` answers one pick per lot it takes from,
    in lot-id order, where each part's picks sum to its stocked need and no pick passes its
    lot's available stock; every named unit is in the pick of its own lot; each pick's units
    are its lot's named units, then its other in-stock units in code order, as many as its
    quantity allows, before any loose piece; and nothing is taken of a part with no stocked
    need.

    **Validates: Requirements 2.4, 2.5, 3.1, 3.2, 3.3, 14.3**
    """
    needs, stock, named = scenario.needs, scenario.stock, scenario.named
    reservation = Reservation.choose(needs, stock, named)

    lots = {lot.lot_id: lot for lot in stock.lots}
    part_of = {lot.lot_id: lot.part_id for lot in stock.lots}

    # One pick per lot, in lot-id order, each within its lot's available stock.
    pick_lots = [pick.lot_id for pick in reservation.picks]
    assert pick_lots == sorted(pick_lots)
    assert len(pick_lots) == len(set(pick_lots))
    for pick in reservation.picks:
        assert pick.quantity >= 1
        assert pick.quantity <= lots[pick.lot_id].available
        assert len(pick.unit_ids) <= pick.quantity

    # Each part's picks sum to its stocked need; a part with no need is untouched.
    taken: dict[PartId, int] = {}
    for pick in reservation.picks:
        taken[part_of[pick.lot_id]] = taken.get(part_of[pick.lot_id], 0) + pick.quantity
    for part_id in {lot.part_id for lot in stock.lots}:
        assert taken.get(part_id, 0) == needs.get(part_id, 0)

    _check_named_in_own_lot(reservation, stock, named)
    _check_units_first(reservation, stock, named)


def _check_named_in_own_lot(
    reservation: Reservation, stock: ReservableStock, named: Sequence[UnitId]
) -> None:
    picks = {pick.lot_id: pick for pick in reservation.picks}
    for unit_id in named:
        unit = stock.named[unit_id]
        assert unit_id in picks[unit.lot_id].unit_ids


def _check_units_first(
    reservation: Reservation, stock: ReservableStock, named: Sequence[UnitId]
) -> None:
    named_set = set(named)
    units_by_lot: dict[LotId, list[StockUnit]] = {}
    for unit in stock.units:
        units_by_lot.setdefault(unit.lot_id, []).append(unit)
    for pick in reservation.picks:
        in_stock = [unit for unit in units_by_lot.get(pick.lot_id, []) if unit.in_stock]
        expected_named = [u for u in named if stock.named[u].lot_id == pick.lot_id]
        free_units = sorted(
            (u for u in in_stock if u.unit_id not in named_set), key=lambda u: u.code
        )
        available_pieces = pick.quantity - len(expected_named)
        chosen = [u.unit_id for u in free_units[:available_pieces]]
        assert pick.unit_ids == (*expected_named, *chosen)


@given(scenario=scenarios())
def test_property_4_no_named_units_draws_the_fewest_lots(scenario: Scenario) -> None:
    """The tail of property 4: with no named units, each part's lots are taken by available
    stock, most first, ties by location code, all but the last giving all they have, so the
    picks draw on as few lots as any choice covering the need could."""
    needs, stock = scenario.needs, scenario.stock
    reservation = Reservation.choose(needs, stock, named=[])

    lots = {lot.lot_id: lot for lot in stock.lots}
    by_part: dict[PartId, list[LotPick]] = {}
    for pick in reservation.picks:
        by_part.setdefault(lots[pick.lot_id].part_id, []).append(pick)

    for part_id, picks in by_part.items():
        ordered = sorted(
            picks,
            key=lambda pick: (-lots[pick.lot_id].available, lots[pick.lot_id].location_code),
        )
        # Every lot but the last is drained to its available stock; the fewest lots that
        # covers the need, since the largest go first.
        for pick in ordered[:-1]:
            assert pick.quantity == lots[pick.lot_id].available
        availables = [lot.available for lot in stock.lots if lot.part_id == part_id]
        assert len(picks) == _fewest_lots(needs[part_id], availables)


def _fewest_lots(need: int, availables: list[int]) -> int:
    """How many lots the largest-first choice draws on to cover the need."""
    count = 0
    for available in sorted(availables, reverse=True):
        if need <= 0:
            break
        need -= available
        count += 1
    return count


# --- Property 5 ------------------------------------------------------------------------------


@st.composite
def _check_part(
    draw: st.DrawFn, part: PartId, start_code: int
) -> tuple[int | None, PartFacts | None, ReservableLot, list[StockUnit], int]:
    """One part for a named-unit case: a stocked need with some in-stock (or not) units, a
    consumable with a unit, or a part the facts don't hold. Returns its need (or None), facts
    (or None), its lot, its units, and the next code."""
    role = draw(st.sampled_from(["stocked", "consumable", "unknown"]))
    lot = a_lot(part, f"WX-L-{draw(st.integers(1, 40)):04d}", draw(st.integers(0, 5)))
    units: list[StockUnit] = []
    code = start_code
    if role == "stocked":
        for _ in range(draw(st.integers(0, 4))):
            units.append(a_unit(part, lot.lot_id, f"WX-U-{code:04d}", in_stock=draw(st.booleans())))
            code += 1
        return draw(st.integers(1, 4)), facts_of(part), lot, units, code
    facts = facts_of(part, not_stocked=True) if role == "consumable" else None
    units.append(a_unit(part, lot.lot_id, f"WX-U-{code:04d}"))
    return None, facts, lot, units, code + 1


@st.composite
def named_check_scenarios(draw: st.DrawFn) -> NamedCheck:
    """Needs, facts, locked stock and a list of named units, valid or not, for the checks.

    Some parts have a stocked need, some are consumables (no need), some are unknown to the
    facts. Units sit in the parts' lots, in stock or not. The named list is drawn from the
    units, another workspace's id, and repeats, so every check has inputs that trip it and
    inputs that don't.
    """
    needs: dict[PartId, int] = {}
    facts: dict[PartId, PartFacts] = {}
    lots: list[ReservableLot] = []
    units: list[StockUnit] = []
    code = 1
    for _ in range(draw(st.integers(1, 4))):
        part = PartId(uuid7())
        need, part_facts, lot, part_units, code = draw(_check_part(part, code))
        if need is not None:
            needs[part] = need
        if part_facts is not None:
            facts[part] = part_facts
        lots.append(lot)
        units.extend(part_units)

    stock = stock_of(lots, units=units, named=units)
    # The named list: drawn units, an id no workspace holds, and repeats.
    pool: list[UnitId] = [unit.unit_id for unit in units]
    pool.append(UnitId(UUID(int=0)))  # a unit the workspace doesn't hold
    named = draw(st.lists(st.sampled_from(pool), max_size=6))
    return NamedCheck(needs, facts, named, stock)


@given(scenario=named_check_scenarios())
def test_property_5_named_units_are_refused_exactly_by_their_rules(
    scenario: NamedCheck,
) -> None:
    """Property 5: named units are refused exactly by their rules.

    For any needs, part facts, locked stock and list of named units, `check_named_units`
    refuses exactly when a unit is named twice, is missing from `stock.named`, is of a part
    with no stocked need, is past its part's need counting in the order named, or is not in
    stock or past what its lot's available stock covers; it raises the error of the first of
    those five checks any unit fails, naming the first unit, in the order named, that fails
    it, and accepts every other list, the empty one included.

    **Validates: Requirements 2.7, 3.4, 3.5**
    """
    needs, facts, named, stock = (
        scenario.needs,
        scenario.facts,
        scenario.named,
        scenario.stock,
    )
    expected = _first_failure(needs, named, stock)

    if expected is None:
        check_named_units(needs, facts, named, stock)  # accepts
        return

    error_type, unit_id = expected
    with pytest.raises(error_type) as caught:
        check_named_units(needs, facts, named, stock)
    assert caught.value.unit_id == unit_id
    assert caught.value.transition is Transition.RESERVE


def _first_failure(
    needs: Mapping[PartId, int], named: Sequence[UnitId], stock: ReservableStock
) -> _Failure:
    """The check the design runs, restated independently: the five in order, the first unit
    each catches. `None` when every check passes."""
    return (
        _repeated(named)
        or _unknown(named, stock)
        or _not_needed(needs, named, stock)
        or _too_many(needs, named, stock)
        or _not_in_stock(named, stock)
    )


def _repeated(named: Sequence[UnitId]) -> _Failure:
    seen: set[UnitId] = set()
    for unit_id in named:
        if unit_id in seen:
            return (RepeatedUnitError, unit_id)
        seen.add(unit_id)
    return None


def _unknown(named: Sequence[UnitId], stock: ReservableStock) -> _Failure:
    return next(
        ((UnknownUnitError, unit_id) for unit_id in named if unit_id not in stock.named), None
    )


def _not_needed(
    needs: Mapping[PartId, int], named: Sequence[UnitId], stock: ReservableStock
) -> _Failure:
    return next(
        (
            (UnitNotNeededError, unit_id)
            for unit_id in named
            if stock.named[unit_id].part_id not in needs
        ),
        None,
    )


def _too_many(
    needs: Mapping[PartId, int], named: Sequence[UnitId], stock: ReservableStock
) -> _Failure:
    counted: dict[PartId, int] = {}
    for unit_id in named:
        part = stock.named[unit_id].part_id
        counted[part] = counted.get(part, 0) + 1
        if counted[part] > needs[part]:
            return (TooManyUnitsError, unit_id)
    return None


def _not_in_stock(named: Sequence[UnitId], stock: ReservableStock) -> _Failure:
    available = {lot.lot_id: lot.available for lot in stock.lots}
    taken: dict[LotId, int] = {}
    for unit_id in named:
        unit = stock.named[unit_id]
        taken[unit.lot_id] = taken.get(unit.lot_id, 0) + 1
        if not unit.in_stock or taken[unit.lot_id] > available.get(unit.lot_id, 0):
            return (UnitNotInStockError, unit_id)
    return None


def test_the_empty_list_is_accepted() -> None:
    part = PartId(uuid7())
    stock = stock_of([a_lot(part, "WX-L-0001", 5)])
    check_named_units({part: 2}, {part: facts_of(part)}, [], stock)  # no raise


def test_a_repeated_unit_is_named() -> None:
    part = PartId(uuid7())
    lot = a_lot(part, "WX-L-0001", 3)
    unit = a_unit(part, lot.lot_id, "WX-U-0001")
    stock = stock_of([lot], units=[unit], named=[unit])

    with pytest.raises(RepeatedUnitError) as caught:
        check_named_units({part: 2}, {part: facts_of(part)}, [unit.unit_id, unit.unit_id], stock)
    assert caught.value.unit_id == unit.unit_id
    assert caught.value.unit_code is None  # repeat is caught before the code is read


def test_a_consumables_unit_is_not_needed() -> None:
    wire = PartId(uuid7())
    lot = a_lot(wire, "WX-L-0001", 5)
    unit = a_unit(wire, lot.lot_id, "WX-U-0007")
    stock = stock_of([lot], units=[unit], named=[unit])

    # A consumable has no stocked need, so its unit is refused as not needed (requirement 2.7).
    with pytest.raises(UnitNotNeededError) as caught:
        check_named_units({}, {wire: facts_of(wire, not_stocked=True)}, [unit.unit_id], stock)
    assert caught.value.unit_code == "WX-U-0007"
