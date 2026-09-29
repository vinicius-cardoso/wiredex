"""`CatalogNetlistPins`, and the pin vocabulary projects keeps apart from catalog's.

Projects writes 02's pin-number grammar again (11's decision 13), so these hold the two copies
to each other: over any text, both accept it as the same number or both refuse it, and the two
type enumerations hold the same values. A reference stored as `U1.a1` has to find ball `A1`.
"""

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from support.catalog import BENCH, World
from wiredex.bootstrap.netlist import CatalogNetlistPins
from wiredex.catalog.domain.errors import CatalogError
from wiredex.catalog.domain.pinout import PinNumber as CatalogPinNumber
from wiredex.catalog.domain.pinout import PinType as CatalogPinType
from wiredex.catalog.domain.pinout import RawPin
from wiredex.projects.domain.errors import InvalidPinReferenceError
from wiredex.projects.domain.pins import PinNumber, PinType
from wiredex.projects.domain.values import PartId

pytestmark = pytest.mark.anyio

# Mostly the characters a pin number is made of, with look-alikes, spaces and a few others, so
# both acceptance and refusal are drawn often.
PIN_TEXT = st.text(
    st.sampled_from([*"aAzZ019_.+-", " ", "\uff21", "\uff11", "Ω", "/", "é"]), max_size=18
)


@given(PIN_TEXT)
def test_both_copies_of_the_grammar_agree(text: str) -> None:
    try:
        catalog = str(CatalogPinNumber(text))
    except CatalogError:
        catalog = None
    try:
        projects = str(PinNumber(text))
    except InvalidPinReferenceError:
        projects = None
    assert projects == catalog


def test_both_type_enumerations_hold_the_same_values() -> None:
    assert {kind.value for kind in PinType} == {kind.value for kind in CatalogPinType}


async def test_pinouts_arrive_in_projects_words_and_a_part_without_pins_is_absent() -> None:
    world = World()
    sensor = world.add_part(world.resistors, "BME280")
    bare = world.add_part(world.resistors, "10k")
    await world.replace_pinout(
        BENCH,
        sensor.id,
        (
            RawPin(number="3", label="SDI", type="io", functions=("SDA", "MOSI"), voltage="3V3"),
            RawPin(number="1", label="GND", type="ground"),
        ),
    )

    async with world.catalog.for_workspace(BENCH) as work:
        found = await CatalogNetlistPins(work).of_parts([PartId(sensor.id), PartId(bare.id)])

    (pins,) = found.values()
    sdi, gnd = pins.pins
    assert list(found) == [PartId(sensor.id)]
    assert (str(sdi.number), sdi.label, sdi.type, sdi.functions) == (
        "3",
        "SDI",
        PinType.IO,
        ("SDA", "MOSI"),
    )
    assert sdi.voltage == Decimal("3.3")
    assert (gnd.type, gnd.voltage) == (PinType.GROUND, None)
