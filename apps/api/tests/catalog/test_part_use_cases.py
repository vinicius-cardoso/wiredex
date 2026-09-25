"""The part use cases over the in-memory catalog.

The bench is *Passives → Resistors* with a required `resistance` in ohms, so `4k7` is the
one value a resistor here needs and everything else is a schema change away.
"""

from collections.abc import Mapping
from decimal import Decimal
from uuid import uuid7

import pytest

from support.catalog import BENCH, OHM, World
from wiredex.catalog.application.attributes import NewAttribute
from wiredex.catalog.application.categories import NewCategory
from wiredex.catalog.application.parts import NewPart, PartRevision
from wiredex.catalog.application.ports import PartQuery
from wiredex.catalog.domain.errors import CatalogError, DuplicateMpnError, PartNotFoundError
from wiredex.catalog.domain.part import PartDefinition, PartDetails
from wiredex.catalog.domain.pinout import RawPin
from wiredex.catalog.domain.schema import AttributeProblemKind
from wiredex.catalog.domain.values import (
    AttributeKey,
    AttributeKind,
    AttributeLabel,
    CategoryName,
    Manufacturer,
    Mpn,
    PartDefinitionId,
    PartName,
    SiValue,
)

pytestmark = pytest.mark.anyio

FOUR_K_SEVEN: Mapping[str, object] = {"resistance": "4k7"}
RESISTANCE = AttributeKey("resistance")
# Enough of a pin table for a part to have one: what it holds is the pinout tests' business.
TWO_PINS = (
    RawPin(number="1", label="GND", type="ground"),
    RawPin(number="2", label="VDD", type="power", voltage="3V3"),
)
TOLERANCE = NewAttribute(
    AttributeKey("tolerance"),
    AttributeLabel("Tolerance"),
    AttributeKind.ENUM,
    required=True,
    options=("1%", "5%"),
)


def details(
    name: str = "R 4k7 0805", manufacturer: str | None = None, mpn: str | None = None
) -> PartDetails:
    return PartDetails(
        PartName(name),
        None if manufacturer is None else Manufacturer(manufacturer),
        None if mpn is None else Mpn(mpn),
    )


async def a_resistor(world: World, typed: Mapping[str, object] = FOUR_K_SEVEN) -> PartDefinition:
    return await world.define_part(BENCH, NewPart(world.resistors.id, details(), typed))


async def a_flagged_resistor(world: World) -> PartDefinition:
    """A resistor defined before *Resistors* asked for a tolerance, so it now needs review."""
    part = await a_resistor(world)
    await world.define_attribute(BENCH, world.resistors.id, TOLERANCE)
    return part


async def test_a_part_stores_every_value_the_resolved_schema_accepted() -> None:
    # Requirement 4.1, against the resolved schema: *mounting* is the parent's field.
    world = World()
    await world.define_attribute(
        BENCH,
        world.passives.id,
        NewAttribute(
            AttributeKey("mounting"),
            AttributeLabel("Mounting"),
            AttributeKind.ENUM,
            options=("through-hole", "smd"),
        ),
    )

    part = await a_resistor(world, {"resistance": "4k7", "mounting": "smd"})

    assert part.workspace_id == BENCH
    assert part.category_id == world.resistors.id
    assert dict(part.attributes) == {
        RESISTANCE: SiValue(Decimal(4700)),
        AttributeKey("mounting"): "smd",
    }
    assert world.catalog.parts.saved[part.id] is part
    assert world.catalog.opened_for == [BENCH, BENCH]


@pytest.mark.parametrize(
    ("typed", "message"),
    [
        pytest.param({}, "resistance is required", id="a required value missing"),
        pytest.param(
            {"resistance": "4k7", "resistence": "4k7"}, "not an attribute", id="an unknown key"
        ),
        pytest.param({"resistance": "4K7"}, "resistance", id="kelvin where kilo was meant"),
        pytest.param({"resistance": True}, "takes a number", id="a switch where a number goes"),
    ],
)
async def test_a_part_the_schema_refuses_is_never_stored(
    typed: Mapping[str, object], message: str
) -> None:
    # Requirements 4.2 to 4.5, validated before anything is written.
    world = World()

    with pytest.raises(CatalogError, match=message):
        await a_resistor(world, typed)

    assert world.catalog.parts.saved == {}
    assert world.catalog.commits == 0


async def test_an_mpn_another_part_already_uses_is_refused_whatever_the_case() -> None:
    # Requirement 4.6: folded on both sides, as the partial unique index folds it.
    world = World()
    await world.define_part(
        BENCH,
        NewPart(world.resistors.id, details("R 4k7 1%", "Yageo", "RC0805FR-074K7L"), FOUR_K_SEVEN),
    )

    with pytest.raises(DuplicateMpnError, match="already used by"):
        await world.define_part(
            BENCH,
            NewPart(world.resistors.id, details("Clone", "yageo", "rc0805fr-074k7l"), FOUR_K_SEVEN),
        )

    assert len(world.catalog.parts.saved) == 1


async def test_the_same_mpn_with_no_manufacturer_collides_too() -> None:
    # A missing manufacturer folds to the empty string; NULL would let both through.
    world = World()
    await world.define_part(BENCH, NewPart(world.resistors.id, details(mpn="R-4K7"), FOUR_K_SEVEN))

    with pytest.raises(DuplicateMpnError):
        await world.define_part(
            BENCH, NewPart(world.resistors.id, details("Second", mpn="r-4k7"), FOUR_K_SEVEN)
        )


async def test_any_number_of_parts_may_go_without_an_mpn() -> None:
    world = World()

    for name in ("R 4k7 0805", "R 10k 0805"):
        await world.define_part(BENCH, NewPart(world.resistors.id, details(name), FOUR_K_SEVEN))

    assert len(world.catalog.parts.saved) == 2


async def test_a_part_is_never_in_conflict_with_its_own_mpn() -> None:
    world = World()
    part = await world.define_part(
        BENCH, NewPart(world.resistors.id, details("R 4k7", "Yageo", "RC0805"), FOUR_K_SEVEN)
    )

    updated = await world.update_part(
        BENCH, part.id, PartRevision(details("R 4k7 1%", "Yageo", "RC0805"), FOUR_K_SEVEN)
    )

    assert str(updated.part.name) == "R 4k7 1%"


async def test_an_update_that_changes_nothing_commits_nothing() -> None:
    # Requirement 4.9, and 3.4 underneath it: 4k7 and 4700 are the same stored number.
    world = World()
    part = await a_resistor(world)
    committed = world.catalog.commits

    await world.update_part(BENCH, part.id, PartRevision(details(), {"resistance": "4700"}))

    assert world.catalog.commits == committed


async def test_an_update_replaces_the_whole_attribute_map() -> None:
    # Requirement 4.8: no merge, so an optional value is cleared by leaving it out.
    world = World()
    await world.define_attribute(
        BENCH,
        world.resistors.id,
        NewAttribute(AttributeKey("notes"), AttributeLabel("Notes"), AttributeKind.TEXT),
    )
    part = await a_resistor(world, {"resistance": "4k7", "notes": "bin 3"})

    updated = await world.update_part(BENCH, part.id, PartRevision(details(), FOUR_K_SEVEN))

    assert dict(updated.part.attributes) == {RESISTANCE: SiValue(Decimal(4700))}


async def test_a_part_cannot_move_to_a_category_its_values_do_not_fit() -> None:
    # Requirement 4.10: *Passives* doesn't define resistance, so the move is refused.
    world = World()
    part = await a_resistor(world)
    committed = world.catalog.commits

    with pytest.raises(CatalogError, match="not an attribute"):
        await world.update_part(
            BENCH, part.id, PartRevision(details(), FOUR_K_SEVEN, world.passives.id)
        )

    assert part.category_id == world.resistors.id
    assert world.catalog.commits == committed


async def test_a_part_moves_to_a_category_that_inherits_the_same_field() -> None:
    world = World()
    part = await a_resistor(world)
    thick_film = await world.create_category(
        BENCH, NewCategory(CategoryName("Thick film"), world.resistors.id)
    )

    moved = await world.update_part(
        BENCH, part.id, PartRevision(details(), FOUR_K_SEVEN, thick_film.id)
    )

    assert moved.part.category_id == thick_film.id
    assert dict(moved.part.attributes) == {RESISTANCE: SiValue(Decimal(4700))}


async def test_a_part_is_read_with_how_many_pins_it_has() -> None:
    """Requirement 1.8: the page needs to know whether there is a pin table, not what's in it.

    Counted, so a part with forty pins costs a read no more than a resistor does, and an edit
    answers with the count too: a patch leaves the pinout exactly where it was.
    """
    world = World()
    part = await a_resistor(world)

    assert (await world.get_part(BENCH, part.id)).pin_count == 0

    await world.replace_pinout(BENCH, part.id, TWO_PINS)

    assert (await world.get_part(BENCH, part.id)).pin_count == 2
    edited = await world.update_part(
        BENCH, part.id, PartRevision(details("R 4k7 1%"), FOUR_K_SEVEN)
    )
    assert edited.pin_count == 2


async def test_a_part_flagged_by_a_later_required_field_is_still_readable() -> None:
    # Requirements 5.2 and 5.4: reading a part that no longer fits succeeds.
    world = World()
    part = await a_flagged_resistor(world)

    view = await world.get_part(BENCH, part.id)

    assert view.needs_review
    assert [(str(p.key), p.problem) for p in view.problems] == [
        ("tolerance", AttributeProblemKind.MISSING_REQUIRED)
    ]
    # And the value typed before the schema changed is untouched (requirement 5.1).
    assert dict(view.part.attributes) == {RESISTANCE: SiValue(Decimal(4700))}


async def test_saving_a_flagged_part_has_to_fix_every_problem_at_once() -> None:
    # Requirement 5.6: the map is validated whole, so a part can't be saved half-fixed.
    world = World()
    part = await a_flagged_resistor(world)

    with pytest.raises(CatalogError, match="tolerance is required"):
        await world.update_part(BENCH, part.id, PartRevision(details(), FOUR_K_SEVEN))

    await world.update_part(
        BENCH, part.id, PartRevision(details(), {"resistance": "4k7", "tolerance": "1%"})
    )

    assert (await world.get_part(BENCH, part.id)).problems == ()


async def test_a_value_a_removed_field_left_behind_is_valid_again_when_the_key_returns() -> None:
    # Requirement 5.5, which is the whole point of keeping the value: it is recoverable.
    world = World()
    part = await a_resistor(world)

    await world.remove_attribute(BENCH, world.resistance.id)
    orphaned = await world.get_part(BENCH, part.id)

    assert [(str(p.key), p.problem) for p in orphaned.problems] == [
        ("resistance", AttributeProblemKind.UNKNOWN_KEY)
    ]

    await world.define_attribute(
        BENCH,
        world.resistors.id,
        NewAttribute(RESISTANCE, AttributeLabel("Resistance"), AttributeKind.NUMBER, OHM),
    )

    assert (await world.get_part(BENCH, part.id)).problems == ()


async def test_the_part_list_narrows_by_name_and_by_category() -> None:
    world = World()
    capacitors = world.add_category("Capacitors")
    for name in ("R 4k7 0805", "R 10k 0805", "R 100R 0805"):
        await world.define_part(BENCH, NewPart(world.resistors.id, details(name), FOUR_K_SEVEN))
    world.add_part(capacitors, "C 100n 0603")

    everything = await world.list_parts(BENCH, PartQuery())
    assert len(everything.items) == 4
    assert everything.next_cursor is None

    in_resistors = await world.list_parts(BENCH, PartQuery(category_id=world.resistors.id))
    assert len(in_resistors.items) == 3

    searched = await world.list_parts(BENCH, PartQuery(text="10K"))
    assert [str(part.name) for part in searched.items] == ["R 10k 0805"]


async def test_a_page_carries_the_cursor_the_next_one_starts_from() -> None:
    world = World()
    for name in ("R 4k7 0805", "R 10k 0805", "R 100R 0805"):
        await world.define_part(BENCH, NewPart(world.resistors.id, details(name), FOUR_K_SEVEN))

    first = await world.list_parts(BENCH, PartQuery(limit=2))

    assert len(first.items) == 2
    assert first.next_cursor is not None

    rest = await world.list_parts(
        BENCH, PartQuery(limit=2, after=PartDefinitionId(first.next_cursor))
    )

    assert len(rest.items) == 1
    assert rest.next_cursor is None


async def test_a_part_is_deleted() -> None:
    world = World()
    part = await a_resistor(world)

    await world.delete_part(BENCH, part.id)

    assert world.catalog.parts.saved == {}


async def test_an_unknown_part_is_simply_not_found() -> None:
    world = World()
    missing = PartDefinitionId(uuid7())

    with pytest.raises(PartNotFoundError):
        await world.get_part(BENCH, missing)
    with pytest.raises(PartNotFoundError):
        await world.delete_part(BENCH, missing)

    assert world.catalog.commits == 0
