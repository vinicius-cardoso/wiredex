from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid7

from wiredex.catalog.domain.category import Category
from wiredex.catalog.domain.part import PartDefinition, PartDetails
from wiredex.catalog.domain.schema import AttributeValues
from wiredex.catalog.domain.values import (
    AttributeKey,
    CategoryId,
    CategoryName,
    Manufacturer,
    Mpn,
    Package,
    PartDefinitionId,
    PartName,
    SiValue,
    WorkspaceId,
)

NOW = datetime(2026, 9, 25, 10, 0, tzinfo=UTC)
LATER = NOW + timedelta(days=2)
BENCH = WorkspaceId(uuid7())

RESISTANCE = AttributeKey("resistance")
TOLERANCE = AttributeKey("tolerance")
DETAILS = PartDetails(
    PartName("Resistor 4.7k 1%"), Manufacturer("Yageo"), Mpn("RC0805FR-074K7L"), Package("0805")
)


def category(name: str = "Resistors") -> Category:
    return Category(CategoryId(uuid7()), BENCH, None, CategoryName(name), NOW)


def values(resistance: str = "4700", **rest: object) -> AttributeValues:
    """What a schema hands back: keys and values already coerced, never raw client input."""
    return AttributeValues({RESISTANCE: SiValue(Decimal(resistance)), **_keyed(rest)})


def _keyed(rest: dict[str, object]) -> dict[AttributeKey, object]:
    return {AttributeKey(key): value for key, value in rest.items()}


def a_part(
    details: PartDetails = DETAILS, attributes: AttributeValues | None = None
) -> tuple[PartDefinition, Category]:
    resistors = category()
    # `is None`, not `or`: an empty attribute map is falsy and is a part worth defining.
    stored = values() if attributes is None else attributes
    part = PartDefinition.define(PartDefinitionId(uuid7()), resistors, details, stored, NOW)
    return part, resistors


def test_a_new_part_belongs_to_the_workspace_of_the_category_it_is_filed_under() -> None:
    # Taking the workspace from the category is what stops a part from landing in one
    # workspace under a category of another.
    part, resistors = a_part()

    assert part.workspace_id == resistors.workspace_id
    assert part.category_id == resistors.id
    assert part.details == DETAILS
    assert part.created_at == part.updated_at == NOW


def test_a_part_needs_nothing_but_a_name() -> None:
    part, _ = a_part(PartDetails(PartName("Mystery resistor")), AttributeValues())

    assert part.manufacturer is None
    assert part.mpn is None
    assert part.package is None
    assert dict(part.attributes) == {}


def test_revising_a_part_stores_the_new_details_and_stamps_when_it_happened() -> None:
    part, _ = a_part()

    assert part.revise(PartDetails(PartName("Resistor 4.7k 5%")), values(), LATER)
    assert str(part.name) == "Resistor 4.7k 5%"
    # PartDetails is replaced whole, so the fields left out of the new one are cleared.
    assert part.mpn is None
    assert part.created_at == NOW
    assert part.updated_at == LATER


def test_revising_a_part_with_nothing_new_changes_nothing_and_leaves_the_stamp_alone() -> None:
    # Requirement 4.9: the use case skips the commit on a False, so updated_at has to stay
    # put — an update that did nothing must not look like an edit afterwards.
    part, _ = a_part()

    assert not part.revise(DETAILS, values(), LATER)
    assert part.updated_at == NOW


def test_a_part_is_revised_when_only_its_attributes_move() -> None:
    part, _ = a_part()

    assert part.revise(DETAILS, values("10000"), LATER)
    assert part.attributes[RESISTANCE] == SiValue(Decimal(10000))


def test_an_attribute_map_that_says_the_same_thing_is_not_a_revision() -> None:
    # A revision compares values, not objects: every update builds a fresh AttributeValues,
    # so comparing by identity would make every save look like a change.
    part, _ = a_part()

    assert not part.revise(DETAILS, values(), LATER)


def test_revising_replaces_the_whole_attribute_map_instead_of_merging_into_it() -> None:
    # Requirement 4.8. A merge would let a part keep a value the new map dropped, which is
    # how a part that needed review would stay half-valid after being saved.
    part, _ = a_part(attributes=values(tolerance="1%"))

    part.revise(DETAILS, values(), LATER)

    assert TOLERANCE not in part.attributes


def test_reclassifying_a_part_stores_the_values_the_new_category_accepted() -> None:
    # Requirement 4.10: the same values can fit one category's schema and not another's, so
    # the use case validates against the new schema and passes the result in.
    part, _ = a_part()
    precision = category("Precision resistors")

    part.reclassify(precision.id, values(tolerance="1%"), LATER)

    assert part.category_id == precision.id
    assert part.attributes[TOLERANCE] == "1%"
    assert part.updated_at == LATER


def test_reclassifying_a_part_never_moves_it_to_another_workspace() -> None:
    # Which is why reclassify takes a CategoryId and not a Category: there is one workspace
    # in play, the part's own, and the use case has already looked the category up in it.
    part, _ = a_part()

    part.reclassify(CategoryId(uuid7()), values(), LATER)

    assert part.workspace_id == BENCH
