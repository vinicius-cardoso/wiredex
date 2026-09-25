from collections.abc import Mapping
from dataclasses import replace
from decimal import Decimal
from uuid import uuid7

import pytest

from wiredex.catalog.domain.errors import (
    CatalogError,
    DuplicateAttributeKeyError,
    InvalidAttributeOptionsError,
)
from wiredex.catalog.domain.schema import (
    AttributeDefinition,
    AttributeProblemKind,
    AttributeSchema,
    AttributeValues,
)
from wiredex.catalog.domain.values import (
    AttributeDefinitionId,
    AttributeKey,
    AttributeKind,
    AttributeLabel,
    CategoryId,
    SiValue,
    Unit,
    WorkspaceId,
)

BENCH = WorkspaceId(uuid7())
PASSIVES = CategoryId(uuid7())
RESISTORS = CategoryId(uuid7())
OHM = Unit("Ω")


def attribute(
    key: str,
    kind: AttributeKind = AttributeKind.TEXT,
    *,
    required: bool = False,
    options: tuple[str, ...] = (),
    unit: Unit | None = None,
) -> AttributeDefinition:
    """A definition of *Resistors* at position 0. `replace` moves it or gives it a position."""
    return AttributeDefinition(
        AttributeDefinitionId(uuid7()),
        BENCH,
        RESISTORS,
        AttributeKey(key),
        AttributeLabel(key),
        kind,
        unit,
        required,
        options,
    )


# *Passives → Resistors*: one definition inherited from the parent, four of the child's own,
# each with the position the form shows it at.
MOUNTING = replace(
    attribute("mounting", AttributeKind.ENUM, options=("through-hole", "smd")),
    category_id=PASSIVES,
)
RESISTANCE = attribute("resistance", AttributeKind.NUMBER, required=True, unit=OHM)
TOLERANCE = replace(
    attribute("tolerance", AttributeKind.ENUM, options=("1%", "5%", "10%")), position=1
)
ROHS = replace(attribute("rohs", AttributeKind.BOOL), position=2)
NOTES = replace(attribute("notes"), position=3)
OWN = [RESISTANCE, TOLERANCE, ROHS, NOTES]

# What the owner typed for one resistor, in the shapes a client sends.
FITTING: Mapping[str, object] = {
    "mounting": "smd",
    "resistance": "4k7",
    "tolerance": "5%",
    "rohs": True,
    "notes": "  bin 3  ",
}


def resistors() -> AttributeSchema:
    return AttributeSchema.inherited([[MOUNTING], OWN])


def keys(schema: AttributeSchema) -> list[str]:
    return [str(definition.key) for definition in schema]


def test_a_categorys_own_definitions_come_after_the_ones_it_inherits() -> None:
    # The chain arrives root first, so the form asks the general questions before the
    # specific ones, and requirement 2.7's "ancestor depth, then position" holds.
    assert keys(resistors()) == ["mounting", "resistance", "tolerance", "rohs", "notes"]


def test_position_orders_the_definitions_of_one_category() -> None:
    # A repository returns rows in whatever order it likes; the schema is what sorts them.
    assert keys(AttributeSchema.inherited([[NOTES, RESISTANCE, TOLERANCE]])) == [
        "resistance",
        "tolerance",
        "notes",
    ]


def test_a_child_may_not_shadow_a_key_it_inherits() -> None:
    # Requirement 2.6: "which definition applies" has to have one answer.
    shadow = replace(MOUNTING, category_id=RESISTORS)

    with pytest.raises(DuplicateAttributeKeyError, match="mounting"):
        AttributeSchema.inherited([[MOUNTING], [shadow]])


def test_a_key_defined_twice_in_one_category_is_refused_the_same_way() -> None:
    with pytest.raises(DuplicateAttributeKeyError, match="resistance"):
        AttributeSchema.inherited([[RESISTANCE, replace(RESISTANCE, position=9)]])


def test_a_schema_answers_which_definition_a_key_resolves_to() -> None:
    schema = resistors()

    assert len(schema) == 5
    assert AttributeKey("resistance") in schema
    assert schema.get(AttributeKey("resistance")) is RESISTANCE
    assert schema.get(AttributeKey("inductance")) is None


def test_a_choice_attribute_needs_something_to_choose_from() -> None:
    # Requirement 2.3, in the domain: no path may build an enum nothing can satisfy.
    with pytest.raises(InvalidAttributeOptionsError, match="tolerance is a choice"):
        attribute("tolerance", AttributeKind.ENUM)


def test_a_kind_that_has_no_options_refuses_them() -> None:
    with pytest.raises(InvalidAttributeOptionsError, match="resistance is a number"):
        attribute("resistance", AttributeKind.NUMBER, options=("1%",))


def test_the_options_rule_guards_a_replacement_list_too() -> None:
    # What task 9's UpdateAttribute asks before it swaps the options of a definition.
    with pytest.raises(InvalidAttributeOptionsError, match="tolerance is a choice"):
        TOLERANCE.check_options(())


def test_validate_stores_every_value_in_the_form_its_kind_defines() -> None:
    values = resistors().validate(FITTING)

    # 4k7 on an ohm attribute lands on an exact 4700, and the text arrives trimmed.
    assert dict(values) == {
        AttributeKey("mounting"): "smd",
        AttributeKey("resistance"): SiValue(Decimal(4700)),
        AttributeKey("tolerance"): "5%",
        AttributeKey("rohs"): True,
        AttributeKey("notes"): "bin 3",
    }


def test_validate_refuses_a_part_with_a_required_value_missing() -> None:
    with pytest.raises(CatalogError, match="resistance is required"):
        resistors().validate({"mounting": "smd", "tolerance": "5%"})


def test_leaving_an_optional_attribute_out_and_sending_null_are_the_same() -> None:
    values = resistors().validate({"resistance": "4k7", "notes": None})

    assert AttributeKey("notes") not in values
    assert len(values) == 1


def test_validate_refuses_a_key_the_schema_does_not_define_and_quotes_it_as_typed() -> None:
    # Named as typed because an unknown key is usually a typo of a defined one.
    with pytest.raises(CatalogError, match="'resistence' is not an attribute"):
        resistors().validate({"resistance": "4k7", "resistence": "4k7"})


def test_validate_refuses_a_key_that_could_never_be_an_attribute_key() -> None:
    with pytest.raises(CatalogError, match="'Resistance!' is not an attribute"):
        resistors().validate({"Resistance!": "4k7"})


def test_a_part_that_fits_its_schema_has_nothing_to_review() -> None:
    schema = resistors()

    assert schema.review(schema.validate(FITTING)) == ()


FOOTPRINT = replace(attribute("footprint", required=True), position=4)


@pytest.mark.parametrize(
    ("own", "key", "expected"),
    [
        # A required attribute defined on a category that already has parts (requirement 5.4).
        pytest.param(
            [*OWN, FOOTPRINT],
            "footprint",
            AttributeProblemKind.MISSING_REQUIRED,
            id="missing_required",
        ),
        pytest.param(
            [RESISTANCE, TOLERANCE, ROHS, replace(NOTES, kind=AttributeKind.NUMBER)],
            "notes",
            AttributeProblemKind.WRONG_KIND,
            id="wrong_kind",
        ),
        pytest.param(
            [RESISTANCE, replace(TOLERANCE, options=("1%",)), ROHS, NOTES],
            "tolerance",
            AttributeProblemKind.NOT_IN_OPTIONS,
            id="not_in_options",
        ),
        # The definition is gone; its value stays and is recoverable (requirement 2.10).
        pytest.param(
            [RESISTANCE, TOLERANCE, ROHS], "notes", AttributeProblemKind.UNKNOWN_KEY, id="unknown"
        ),
    ],
)
def test_review_reports_each_attribute_that_no_longer_fits(
    own: list[AttributeDefinition], key: str, expected: AttributeProblemKind
) -> None:
    stored = resistors().validate(FITTING)  # Typed before the change, and never rewritten.

    problems = AttributeSchema.inherited([[MOUNTING], own]).review(stored)

    assert [(str(problem.key), problem.problem) for problem in problems] == [(key, expected)]
    # The message is what the web puts on the field, so it has to name the attribute.
    assert key in problems[0].message
    assert dict(stored) == dict(resistors().validate(FITTING))


def test_values_copy_what_they_are_given_and_offer_no_way_to_change_it() -> None:
    source: dict[AttributeKey, object] = {AttributeKey("notes"): "bin 3"}
    values = AttributeValues(source)

    source[AttributeKey("notes")] = "bin 4"

    assert values[AttributeKey("notes")] == "bin 3"
    assert not hasattr(values, "__setitem__")
    assert "bin 3" in repr(values)


def test_a_part_with_no_attributes_at_all_is_an_empty_map() -> None:
    assert dict(AttributeValues()) == {}
