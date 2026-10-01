"""The part use cases over the in-memory catalog.

The bench is *Passives → Resistors* with a required `resistance` in ohms, so `4k7` is the
one value a resistor here needs and everything else is a schema change away.
"""

from collections.abc import Mapping
from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid7

import pytest

from support.catalog import BENCH, OHM, World
from wiredex.catalog.application.attributes import NewAttribute
from wiredex.catalog.application.categories import NewCategory
from wiredex.catalog.application.parts import NewPart, PartDescription, PartRevision
from wiredex.catalog.application.ports import PartQuery
from wiredex.catalog.domain.category import CategoryFlags
from wiredex.catalog.domain.errors import (
    CatalogError,
    DuplicateMpnError,
    PartInUseError,
    PartNotFoundError,
)
from wiredex.catalog.domain.part import PartDefinition, PartDetails
from wiredex.catalog.domain.pinout import RawPin
from wiredex.catalog.domain.schema import AttributeProblemKind
from wiredex.catalog.domain.usage import PartUsage
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
    thick_film = (
        await world.create_category(
            BENCH, NewCategory(CategoryName("Thick film"), world.resistors.id)
        )
    ).category

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


async def test_a_deleted_part_moves_to_the_trash_and_is_found_no_more() -> None:
    # 16's requirements 1.1 and 2.1: kept, with when it moved, and absent everywhere.
    world = World()
    part = await a_resistor(world)
    world.clock.advance(timedelta(hours=1))

    await world.delete_part(BENCH, part.id)

    assert world.catalog.parts.saved[part.id].trashed_at == world.clock.now()
    with pytest.raises(PartNotFoundError):
        await world.get_part(BENCH, part.id)
    with pytest.raises(PartNotFoundError):
        await world.delete_part(BENCH, part.id)
    assert (await world.list_parts(BENCH, PartQuery())).items == ()


async def test_an_unknown_part_is_simply_not_found() -> None:
    world = World()
    missing = PartDefinitionId(uuid7())

    with pytest.raises(PartNotFoundError):
        await world.get_part(BENCH, missing)
    with pytest.raises(PartNotFoundError):
        await world.delete_part(BENCH, missing)

    assert world.catalog.commits == 0


# --- DeletePart and the bills of materials that keep a part ----------------------------------


async def test_a_part_a_bom_names_is_kept() -> None:
    # 09's requirement 8.1: refused before anything is removed, naming the BOM.
    world = World()
    part = await a_resistor(world)
    [use] = world.part_uses.name(part, "Weather station", "A")
    commits = world.catalog.commits

    with pytest.raises(
        PartInUseError, match="on a bill of materials; take it off first"
    ) as refused:
        await world.delete_part(BENCH, part.id)

    assert refused.value.usage == PartUsage((use,), 1)
    assert part.id in world.catalog.parts.saved
    assert world.catalog.commits == commits
    # Asked in the caller's workspace, for the first three.
    assert world.part_uses.asked == [(BENCH, part.id, 3)]


async def test_five_boms_are_three_named_and_two_more() -> None:
    world = World()
    part = await a_resistor(world)
    uses = world.part_uses.name(part, "Weather station", "A", "B", "C", "D", "E")

    with pytest.raises(PartInUseError, match="is on 5 bills of materials") as refused:
        await world.delete_part(BENCH, part.id)

    assert refused.value.usage.uses == tuple(uses[:3])
    assert refused.value.usage.more == 2


async def test_a_part_no_bom_names_is_deleted_as_before() -> None:
    # 09's requirement 8.2: another part's BOMs don't hold this one.
    world = World()
    part = await a_resistor(world)
    other = world.add_part(world.resistors, "R 10k 0805")
    world.part_uses.name(other, "Weather station", "A")
    commits = world.catalog.commits

    await world.delete_part(BENCH, part.id)

    assert world.catalog.parts.saved[part.id].in_trash
    assert world.catalog.commits == commits + 1


async def test_a_part_already_gone_is_still_not_found_whatever_names_it() -> None:
    # A raced line may still name a deleted part; the part is judged before the BOMs' answer.
    world = World()
    part = await a_resistor(world)
    world.part_uses.name(part, "Weather station", "A")
    del world.catalog.parts.saved[part.id]

    with pytest.raises(PartNotFoundError):
        await world.delete_part(BENCH, part.id)


# --- DescribeParts: several parts and their flags, for other modules ---------------------


def count_reads(world: World, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every call the use case makes into the fake stores, by name: what a read costs."""
    calls: list[str] = []
    reads = {
        world.catalog.parts: ("get", "with_ids", "page"),
        world.catalog.categories: ("get", "all", "ancestors"),
    }
    for store, names in reads.items():
        for name in names:
            original = getattr(store, name)

            async def counted(*args: object, _name: str = name, _original: Any = original) -> Any:
                calls.append(_name)
                return await _original(*args)

            monkeypatch.setattr(store, name, counted)
    return calls


async def test_described_parts_carry_both_flags_inherited_along_the_tree() -> None:
    # 09's requirements 1.2 and 1.3, answered for other modules: Passives sets not stocked,
    # Resistors sets tracking, and a part under each answers what its chain resolves.
    world = World()
    world.passives.not_stocked = True
    world.resistors.tracked_individually = True
    resistor = world.add_part(world.resistors)
    loose = world.add_part(world.passives, "Solder 0.8 mm")

    described = await world.describe_parts(BENCH, [resistor.id, loose.id])

    assert described == {
        resistor.id: PartDescription(resistor, CategoryFlags(True, True)),
        loose.id: PartDescription(loose, CategoryFlags(False, True)),
    }
    assert world.catalog.commits == 0


async def test_an_id_the_catalog_does_not_hold_is_left_out() -> None:
    world = World()
    resistor = world.add_part(world.resistors)
    gone = PartDefinitionId(uuid7())

    assert set(await world.describe_parts(BENCH, [resistor.id, gone])) == {resistor.id}
    assert await world.describe_parts(BENCH, [gone]) == {}


async def test_describing_no_parts_opens_no_unit_of_work() -> None:
    world = World()

    assert await world.describe_parts(BENCH, []) == {}
    assert world.catalog.opened_for == []


@pytest.mark.parametrize("count", [1, 30])
async def test_describing_parts_reads_twice_whatever_their_number(
    count: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 09's requirement 12.3: the parts in one read and the tree in another, never a chain
    # per part.
    world = World()
    thick_film = world.add_category("Thick film", world.resistors)
    parts = [world.add_part(thick_film, f"R {index}k 0805") for index in range(count)]
    calls = count_reads(world, monkeypatch)

    described = await world.describe_parts(BENCH, [part.id for part in parts])

    assert len(described) == count
    assert calls == ["with_ids", "all"]


async def test_a_part_whose_category_left_the_tree_mid_read_answers_the_defaults() -> None:
    # The safe answer when the tree moved under the read: stocked and lot-counted.
    world = World()
    world.passives.not_stocked = True
    resistor = world.add_part(world.resistors)
    del world.catalog.categories.saved[world.resistors.id]

    described = await world.describe_parts(BENCH, [resistor.id])

    assert described[resistor.id].flags == CategoryFlags()
