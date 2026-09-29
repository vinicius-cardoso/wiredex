from collections.abc import Mapping
from decimal import Decimal
from uuid import uuid7

import pytest
from hypothesis import given
from hypothesis import strategies as st

from support.bom import a_line, a_revision, facts_of
from support.netlist import DESIGNATOR_POOL, PIN_POOL, references
from wiredex.projects.domain.bom import BillOfMaterials
from wiredex.projects.domain.errors import (
    AmbiguousPinError,
    InvalidPinReferenceError,
    NoPinsError,
    RepeatedPinError,
    UnknownDesignatorError,
    UnknownNetPartError,
    UnknownPinError,
)
from wiredex.projects.domain.netlist import (
    NetDraft,
    PinReference,
    Resolution,
    ResolutionState,
    TypedReference,
    WireColor,
)
from wiredex.projects.domain.pins import PartPins, PinFacts, PinNumber, PinType
from wiredex.projects.domain.shortage import PartFacts
from wiredex.projects.domain.values import PartId

ESP32, BME280, RESISTOR, GONE = (PartId(uuid7()) for _ in range(4))


def _pins(*rows: tuple[str, str, PinType, str]) -> PartPins:
    return PartPins(
        tuple(
            PinFacts(PinNumber(number), label, kind, tuple(functions.split()), Decimal("3.3"))
            for number, label, kind, functions in rows
        )
    )


PINS: dict[PartId, PartPins] = {
    ESP32: _pins(
        ("1", "3V3", PinType.POWER, ""),
        ("14", "GND", PinType.GROUND, ""),
        ("20", "GND", PinType.GROUND, ""),
        ("25", "GPIO21", PinType.IO, "SDA"),
        ("26", "GND", PinType.GROUND, ""),
    ),
    BME280: _pins(("3", "SDI", PinType.IO, "SDA MOSI"), ("4", "SCK", PinType.INPUT, "SCL")),
}
PARTS: dict[PartId, PartFacts] = {
    ESP32: facts_of(ESP32, "ESP32-DevKitC"),
    BME280: facts_of(BME280, "BME280"),
    RESISTOR: facts_of(RESISTOR, "Resistor 4k7 0805"),
}
REVISION = a_revision()
BOM = (
    BillOfMaterials(REVISION.id)
    .with_line(a_line(REVISION, ESP32, "U1"))
    .with_line(a_line(REVISION, BME280, "U2"))
    .with_line(a_line(REVISION, RESISTOR, "R1, R2"))
    .with_line(a_line(REVISION, GONE, "U9"))
)


def _resolve(text: str) -> PinReference:
    return TypedReference.parse(text).resolve(BOM, PARTS, PINS)


class TestResolve:
    @pytest.mark.parametrize(
        ("typed", "stored"),
        [("U1.25", "U1.25"), ("u1.gpio21", "U1.25"), ("U1.SDA", "U1.25"), ("U2.SDA", "U2.3")],
    )
    def test_matches_number_then_label_then_function_and_stores_the_number(
        self, typed: str, stored: str
    ) -> None:
        assert str(_resolve(typed)) == stored

    def test_a_part_with_no_pinout_takes_the_pin_as_a_number(self) -> None:
        assert str(_resolve("r1.a1")) == "R1.A1"

    def test_a_part_with_no_pinout_refuses_what_isnt_a_pin_number(self) -> None:
        with pytest.raises(InvalidPinReferenceError) as refused:
            _resolve("R1.GND/ADJ")
        assert refused.value.item == "R1.GND/ADJ"

    def test_refuses_a_designator_off_the_bom(self) -> None:
        with pytest.raises(UnknownDesignatorError) as refused:
            _resolve("U3.1")
        assert refused.value.item == "U3.1"

    def test_refuses_a_part_the_catalog_no_longer_holds(self) -> None:
        with pytest.raises(UnknownNetPartError):
            _resolve("U9.1")

    def test_refuses_a_pin_the_pinout_lacks(self) -> None:
        with pytest.raises(UnknownPinError) as refused:
            _resolve("U1.99")
        assert "ESP32-DevKitC has no pin 99" in str(refused.value)

    def test_names_the_candidates_of_an_ambiguous_label(self) -> None:
        with pytest.raises(AmbiguousPinError) as refused:
            _resolve("U1.GND")
        assert refused.value.candidates == ("14", "20", "26")
        assert "could be pins 14, 20 or 26 of ESP32-DevKitC" in str(refused.value)


class TestDraft:
    def test_reads_its_fields_before_any_read(self) -> None:
        draft = NetDraft.parse(" SDA ", "blue", "  ", "U1.SDA, U2.SDA R1.2")
        content = draft.content(BOM, PARTS, PINS)
        assert (str(content.name), content.color, content.notes) == ("SDA", WireColor.BLUE, None)
        assert content.pins.text() == "R1.2, U1.25, U2.3"

    def test_refuses_no_pins(self) -> None:
        with pytest.raises(NoPinsError):
            NetDraft.parse("SDA", None, None, " , ")

    def test_refuses_two_spellings_of_one_pin_naming_the_second(self) -> None:
        draft = NetDraft.parse("SDA", None, None, "U2.3, U2.SDI")
        with pytest.raises(RepeatedPinError) as refused:
            draft.content(BOM, PARTS, PINS)
        assert refused.value.item == "U2.SDI"

    def test_only_new_references_are_resolved(self) -> None:
        draft = NetDraft.parse("SDA", None, None, "U7.3, U1.25")
        kept = frozenset({_ref("U7.3")})
        assert [item.text for item in draft.new_references(kept)] == ["U1.25"]
        assert draft.content(BOM, PARTS, PINS, kept).pins.text() == "U1.25, U7.3"


def _ref(text: str) -> PinReference:
    stored = TypedReference.parse(text).as_stored()
    assert stored is not None
    return stored


# --- Properties ------------------------------------------------------------------------------

POOL_PARTS = tuple(PartId(uuid7()) for _ in DESIGNATOR_POOL)


@st.composite
def worlds(
    draw: st.DrawFn,
) -> tuple[BillOfMaterials, dict[PartId, PartFacts], dict[PartId, PartPins]]:
    """A BOM holding some of the pool's designators, a catalog holding some of their parts, and
    pinouts for some of those, each holding some of the pool's pin numbers."""
    revision = a_revision()
    bom = BillOfMaterials(revision.id)
    parts: dict[PartId, PartFacts] = {}
    pins: dict[PartId, PartPins] = {}
    for designator, part_id in zip(DESIGNATOR_POOL, POOL_PARTS, strict=True):
        if draw(st.booleans()):
            bom = bom.with_line(a_line(revision, part_id, str(designator)))
        if draw(st.booleans()):
            parts[part_id] = facts_of(part_id)
        numbers = draw(st.sets(st.sampled_from(PIN_POOL), max_size=len(PIN_POOL)))
        if numbers:
            pins[part_id] = PartPins(
                tuple(
                    PinFacts(number, f"P{number}", PinType.IO)
                    for number in sorted(numbers, key=str)
                )
            )
    return bom, parts, pins


type World = tuple[BillOfMaterials, Mapping[PartId, PartFacts], Mapping[PartId, PartPins]]


def _expected(reference: PinReference, world: World) -> ResolutionState:
    bom, parts, pins = world
    line = bom.line_with(reference.designator)
    if line is None:
        return ResolutionState.UNKNOWN_DESIGNATOR
    part_id = line.content.part_id
    if part_id not in parts:
        return ResolutionState.UNKNOWN_PART
    if part_id not in pins:
        return ResolutionState.UNCHECKED
    if any(pin.number == reference.pin for pin in pins[part_id].pins):
        return ResolutionState.RESOLVED
    return ResolutionState.UNKNOWN_PIN


# Property 5: resolution follows the BOM and the pinouts, and only them.
@given(worlds(), references)
def test_resolution_follows_the_bom_and_the_pinouts(world: World, reference: PinReference) -> None:
    resolution = Resolution.of(reference, *world)
    assert resolution.state is _expected(reference, world)
    assert (resolution.pin is not None) == (resolution.state is ResolutionState.RESOLVED)


# Property 6: a new reference is stored only when it names a real pin (here by number).
@given(worlds(), references)
def test_a_new_reference_is_stored_only_when_it_is_real(
    world: World, reference: PinReference
) -> None:
    expected = _expected(reference, world)
    typed = TypedReference.parse(str(reference))
    try:
        stored = typed.resolve(*world)
    except UnknownDesignatorError, UnknownNetPartError, UnknownPinError:
        assert expected.unresolved
    else:
        assert expected in {ResolutionState.RESOLVED, ResolutionState.UNCHECKED}
        assert stored == reference


# Property 3: canonical text reads back as the same references, when they resolve by number.
@given(worlds(), st.sets(references, min_size=1, max_size=6))
def test_canonical_text_reads_back(world: World, chosen: set[PinReference]) -> None:
    real = {ref for ref in chosen if not _expected(ref, world).unresolved}
    if not real:
        return
    first = NetDraft.parse("N", None, None, ", ".join(map(str, real))).content(*world)
    again = NetDraft.parse("N", None, None, first.pins.text()).content(*world)
    assert again.pins == first.pins


# Property 7: an edit keeps what it didn't touch, whatever the BOM and pinouts became.
@given(worlds(), st.sets(references, min_size=1, max_size=6), st.sampled_from(WireColor))
def test_an_edit_keeps_what_it_did_not_touch(
    world: World, held: set[PinReference], color: WireColor
) -> None:
    text = ", ".join(map(str, held))
    edited = NetDraft.parse("N", color.value, None, text).content(*world, kept=frozenset(held))
    assert set(edited.pins) == held
    assert edited.color is color
