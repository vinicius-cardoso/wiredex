"""The attribute use cases over the in-memory catalog.

The bench starts as *Passives → Resistors* with a required `resistance` in ohms on
*Resistors*, so an ancestor collision is one definition on *Passives* away.
"""

from decimal import Decimal
from uuid import uuid7

import pytest

from support.catalog import BENCH, World
from wiredex.catalog.application.attributes import AttributeChanges, NewAttribute
from wiredex.catalog.domain.errors import (
    AttributeNotFoundError,
    CatalogError,
    CategoryNotFoundError,
    DuplicateAttributeKeyError,
    InvalidAttributeOptionsError,
)
from wiredex.catalog.domain.schema import AttributeValues
from wiredex.catalog.domain.values import (
    AttributeDefinitionId,
    AttributeKey,
    AttributeKind,
    AttributeLabel,
    CategoryId,
    SiValue,
)

pytestmark = pytest.mark.anyio

STORED = AttributeValues({AttributeKey("resistance"): SiValue(Decimal(4700))})


def new(
    key: str, kind: AttributeKind = AttributeKind.TEXT, options: tuple[str, ...] = ()
) -> NewAttribute:
    return NewAttribute(AttributeKey(key), AttributeLabel(key.capitalize()), kind, options=options)


async def test_an_attribute_is_defined_on_a_category() -> None:
    world = World()

    tolerance = await world.define_attribute(
        BENCH, world.resistors.id, new("tolerance", AttributeKind.ENUM, ("1%", "5%"))
    )

    assert tolerance.category_id == world.resistors.id
    assert tolerance.options == ("1%", "5%")
    assert world.catalog.attribute_definitions.saved[tolerance.id] is tolerance
    assert world.catalog.commits == 1
    assert world.catalog.opened_for == [BENCH]


async def test_a_key_the_category_already_defines_is_refused() -> None:
    world = World()

    with pytest.raises(DuplicateAttributeKeyError, match="resistance is already defined here"):
        await world.define_attribute(BENCH, world.resistors.id, new("resistance"))

    assert len(world.catalog.attribute_definitions.saved) == 1
    assert world.catalog.commits == 0


async def test_a_key_an_ancestor_defines_cannot_be_shadowed() -> None:
    # Requirement 2.6: inheritance is additive, so "which definition applies" keeps one answer.
    world = World()
    await world.define_attribute(
        BENCH, world.passives.id, new("mounting", AttributeKind.ENUM, ("through-hole", "smd"))
    )

    with pytest.raises(DuplicateAttributeKeyError, match="above this one"):
        await world.define_attribute(BENCH, world.resistors.id, new("mounting"))

    assert world.catalog.commits == 1


async def test_a_choice_attribute_with_nothing_to_choose_from_is_refused() -> None:
    world = World()

    with pytest.raises(InvalidAttributeOptionsError, match="tolerance is a choice"):
        await world.define_attribute(
            BENCH, world.resistors.id, new("tolerance", AttributeKind.ENUM)
        )

    assert world.catalog.commits == 0


async def test_an_attribute_cannot_be_defined_on_a_category_that_does_not_exist() -> None:
    world = World()

    with pytest.raises(CategoryNotFoundError):
        await world.define_attribute(BENCH, CategoryId(uuid7()), new("tolerance"))


async def test_the_editable_fields_change_without_touching_a_stored_value() -> None:
    # Requirements 2.8 and 5.1: the part keeps the 4k7 that was typed before the change.
    world = World()
    part = world.add_part(world.resistors, attributes=STORED)

    updated = await world.update_attribute(
        BENCH,
        world.resistance.id,
        AttributeChanges(label=AttributeLabel("Nominal resistance"), required=False, position=3),
    )

    assert str(updated.label) == "Nominal resistance"
    assert updated.required is False
    assert updated.position == 3
    assert dict(part.attributes) == dict(STORED)
    assert world.catalog.commits == 1


async def test_an_update_that_changes_nothing_commits_nothing() -> None:
    world = World()

    await world.update_attribute(
        BENCH, world.resistance.id, AttributeChanges(label=world.resistance.label, required=True)
    )

    assert world.catalog.commits == 0


async def test_a_replacement_option_list_is_held_to_the_same_rule() -> None:
    world = World()
    tolerance = await world.define_attribute(
        BENCH, world.resistors.id, new("tolerance", AttributeKind.ENUM, ("1%", "5%"))
    )

    with pytest.raises(InvalidAttributeOptionsError, match="tolerance is a choice"):
        await world.update_attribute(BENCH, tolerance.id, AttributeChanges(options=()))

    assert tolerance.options == ("1%", "5%")
    assert world.catalog.commits == 1  # the define, not the refused update


@pytest.mark.parametrize(
    ("changes", "what"),
    [
        pytest.param(AttributeChanges(key=AttributeKey("ohms")), "key", id="a new key"),
        pytest.param(AttributeChanges(kind=AttributeKind.TEXT), "kind", id="a new kind"),
    ],
)
async def test_a_key_or_a_kind_cannot_be_changed(changes: AttributeChanges, what: str) -> None:
    # Requirement 2.9. Flag-don't-drop would otherwise flag data the owner never touched.
    world = World()

    with pytest.raises(CatalogError, match=f"{what} can't change: remove the attribute"):
        await world.update_attribute(BENCH, world.resistance.id, changes)

    assert str(world.resistance.key) == "resistance"
    assert world.resistance.kind is AttributeKind.NUMBER
    assert world.catalog.commits == 0


async def test_a_patch_may_send_back_the_key_and_kind_it_read() -> None:
    world = World()

    updated = await world.update_attribute(
        BENCH,
        world.resistance.id,
        AttributeChanges(
            label=AttributeLabel("Resistance in ohms"),
            key=world.resistance.key,
            kind=world.resistance.kind,
        ),
    )

    assert str(updated.label) == "Resistance in ohms"
    assert world.catalog.commits == 1


async def test_removing_an_attribute_keeps_the_values_already_stored_under_it() -> None:
    # Requirement 2.10: the definition goes, the data stays and stays recoverable.
    world = World()
    part = world.add_part(world.resistors, attributes=STORED)

    await world.remove_attribute(BENCH, world.resistance.id)

    assert world.catalog.attribute_definitions.saved == {}
    assert dict(part.attributes) == dict(STORED)
    resolved = await world.get_category_schema(BENCH, world.resistors.id)
    assert AttributeKey("resistance") not in resolved.schema
    assert world.catalog.commits == 1


async def test_an_unknown_attribute_is_simply_not_found() -> None:
    world = World()
    missing = AttributeDefinitionId(uuid7())

    with pytest.raises(AttributeNotFoundError):
        await world.update_attribute(BENCH, missing, AttributeChanges(position=1))
    with pytest.raises(AttributeNotFoundError):
        await world.remove_attribute(BENCH, missing)

    assert world.catalog.commits == 0


async def test_a_schema_carries_the_inherited_definitions_before_the_categorys_own() -> None:
    # Requirement 2.7: ancestor depth first, then position, each marked with where it's from.
    world = World()
    mounting = await world.define_attribute(
        BENCH, world.passives.id, new("mounting", AttributeKind.ENUM, ("through-hole", "smd"))
    )

    resolved = await world.get_category_schema(BENCH, world.resistors.id)

    assert resolved.category is world.resistors
    assert [(str(d.key), d.category_id) for d in resolved.schema] == [
        ("mounting", world.passives.id),
        ("resistance", world.resistors.id),
    ]
    # A parent doesn't inherit from its child.
    passives = await world.get_category_schema(BENCH, world.passives.id)
    assert list(passives.schema) == [mounting]
