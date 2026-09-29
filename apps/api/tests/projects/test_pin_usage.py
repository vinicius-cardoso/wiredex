"""A part's pin uses, grouped under its pins (12-wiring-validation, requirement 7)."""

from uuid import uuid7

from hypothesis import given
from hypothesis import strategies as st

from support.bom import facts_of
from support.netlist import DESIGNATOR_POOL, PIN_POOL
from wiredex.projects.domain.designators import Designator
from wiredex.projects.domain.netlist import NetName, WireColor
from wiredex.projects.domain.pin_usage import PinUsage, PinUse
from wiredex.projects.domain.pins import PartPins, PinFacts, PinNumber, PinType
from wiredex.projects.domain.values import (
    NetId,
    PartId,
    ProjectId,
    ProjectName,
    RevisionId,
    RevisionLabel,
    RevisionStatus,
)

BOARD = facts_of(PartId(uuid7()), "ESP32-DevKitC")


def a_use(pin: str | PinNumber, net: str = "SDA", designator: str = "U1") -> PinUse:
    return PinUse(
        ProjectId(uuid7()),
        ProjectName("Weather station"),
        RevisionId(uuid7()),
        RevisionLabel("A"),
        RevisionStatus.DRAFT,
        Designator.parse(designator),
        pin if isinstance(pin, PinNumber) else PinNumber(pin),
        NetId(uuid7()),
        NetName(net),
        WireColor.BLUE,
    )


def pinout(*numbers: str) -> PartPins:
    return PartPins(tuple(PinFacts(PinNumber(n), f"P{n}", PinType.IO) for n in numbers))


def test_uses_sit_under_their_pins_in_saved_order_with_free_pins_empty() -> None:
    sda, scl, again = a_use("25", "SDA"), a_use("22", "SCL"), a_use("25", "SDA", "U2")

    usage = PinUsage.of(BOARD, pinout("25", "14", "22"), [sda, scl, again])

    assert [(str(pin.number), uses) for pin, uses in usage.pins] == [
        ("25", (sda, again)),
        ("14", ()),
        ("22", (scl,)),
    ]
    assert usage.others == ()
    assert usage.has_pinout


def test_numbers_off_the_pinout_are_other_pins_in_natural_order() -> None:
    uses = [a_use("A10"), a_use("10"), a_use("2"), a_use("A2")]

    usage = PinUsage.of(BOARD, pinout("1"), uses)

    assert [str(number) for number, _ in usage.others] == ["2", "10", "A2", "A10"]


def test_a_part_without_a_pinout_has_every_use_under_other_pins() -> None:
    usage = PinUsage.of(BOARD, None, [a_use("2"), a_use("1"), a_use("2", "GND")])

    assert not usage.has_pinout
    assert usage.pins == ()
    assert [(str(number), len(uses)) for number, uses in usage.others] == [("1", 1), ("2", 2)]


# Property 4: every use lands exactly once, under its pin when the pinout holds its number and
# under other pins otherwise; every pin of the pinout appears once, in saved order.
@given(
    st.lists(st.sampled_from(PIN_POOL), unique=True).map(
        lambda numbers: PartPins(tuple(PinFacts(n, str(n), PinType.IO) for n in numbers))
    ),
    st.lists(st.tuples(st.sampled_from(PIN_POOL), st.sampled_from(DESIGNATOR_POOL))),
)
def test_pin_usage_partitions_the_uses(
    pins: PartPins, drawn: list[tuple[PinNumber, Designator]]
) -> None:
    uses = [a_use(number, designator=str(designator)) for number, designator in drawn]

    usage = PinUsage.of(BOARD, pins if pins.pins else None, uses)

    assert tuple(pin for pin, _ in usage.pins) == pins.pins
    placed = [use for _, held in (*usage.pins, *usage.others) for use in held]
    assert sorted(map(id, placed)) == sorted(map(id, uses))
    held_numbers = {pin.number for pin in pins.pins}
    for pin, held in usage.pins:
        assert all(use.pin == pin.number for use in held)
    for number, held in usage.others:
        assert number not in held_numbers
        assert held
        assert all(use.pin == number for use in held)
    # Each group keeps the order the uses came in (requirement 7.4 is the caller's order).
    for _, held in (*usage.pins, *usage.others):
        assert [uses.index(use) for use in held] == sorted(uses.index(use) for use in held)
