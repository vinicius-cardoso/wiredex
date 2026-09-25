"""Restoring a demo bench's sample catalog, over the in-memory catalog.

The bench here starts empty, unlike the one the other use-case tests share: a reset writes
the whole sample tree, so anything already in it would be something the restore had to
clear rather than something it was given.
"""

from decimal import Decimal

import pytest

from support.catalog import InMemoryCatalog
from support.identity import ManualClock, NewIds
from wiredex.catalog.application.demo import SAMPLE_CATALOG, RestoreSampleCatalog
from wiredex.catalog.domain.category import Category
from wiredex.catalog.domain.part import PartDefinition, PartDetails
from wiredex.catalog.domain.schema import AttributeValues
from wiredex.catalog.domain.values import (
    AttributeKey,
    AttributeKind,
    CategoryId,
    CategoryName,
    PartDefinitionId,
    PartName,
    SiValue,
    Unit,
    WorkspaceId,
)

pytestmark = pytest.mark.anyio

BENCH = WorkspaceId(NewIds().new_id())
RESISTANCE = AttributeKey("resistance")
CAPACITANCE = AttributeKey("capacitance")
TOLERANCE = AttributeKey("tolerance")


class Demo:
    """An empty bench and the restore use case over it."""

    def __init__(self) -> None:
        self.catalog = InMemoryCatalog()
        self.restore = RestoreSampleCatalog(self.catalog.for_workspace, ManualClock(), NewIds())

    def categories(self) -> dict[str, Category]:
        return {c.name.value: c for c in self.catalog.categories.saved.values()}

    def parts(self) -> dict[str, PartDefinition]:
        return {p.name.value: p for p in self.catalog.parts.saved.values()}

    def attributes(self, category: Category) -> dict[str, AttributeKind]:
        saved = self.catalog.attribute_definitions.saved.values()
        return {d.key.value: d.kind for d in saved if d.category_id == category.id}


@pytest.fixture
def demo() -> Demo:
    return Demo()


async def test_a_reset_writes_the_sample_tree(demo: Demo) -> None:
    await demo.restore(BENCH)

    categories = demo.categories()
    assert set(categories) == {"Passives", "Resistors", "Capacitors"}
    assert categories["Passives"].parent_id is None
    assert categories["Resistors"].parent_id == categories["Passives"].id
    assert categories["Capacitors"].parent_id == categories["Passives"].id


async def test_the_sample_schema_measures_each_kind_of_passive(demo: Demo) -> None:
    await demo.restore(BENCH)

    categories = demo.categories()
    assert demo.attributes(categories["Passives"]) == {"tolerance": AttributeKind.ENUM}
    assert demo.attributes(categories["Resistors"]) == {"resistance": AttributeKind.NUMBER}
    assert demo.attributes(categories["Capacitors"]) == {"capacitance": AttributeKind.NUMBER}
    units = {
        d.key.value: d.unit
        for d in demo.catalog.attribute_definitions.saved.values()
        if d.unit is not None
    }
    assert units == {"resistance": Unit("Ω"), "capacitance": Unit("F")}


async def test_the_sample_parts_are_stored_as_the_notation_reads_them(demo: Demo) -> None:
    seeded = await demo.restore(BENCH)

    parts = demo.parts()
    assert seeded == len(parts) == 5
    resistor = parts["Resistor 4k7 0805"]
    # 4k7 typed, 4700 stored, exactly: the demo data goes through the same validation a
    # part from the form does (requirement 3.4).
    assert resistor.attributes[RESISTANCE] == SiValue(Decimal("4700"))
    assert resistor.attributes[TOLERANCE] == "±1 %"
    # 100nF carries the attribute's own unit, which parsing drops (requirement 3.5).
    assert parts["Capacitor 100n 0603 X7R"].attributes[CAPACITANCE] == SiValue(Decimal("1E-7"))
    assert parts["Capacitor 2u2 0805 X5R"].attributes[CAPACITANCE] == SiValue(Decimal("2.2E-6"))


async def test_a_reset_clears_whatever_the_guest_left_behind(demo: Demo) -> None:
    await demo.restore(BENCH)
    theirs = Category(
        CategoryId(NewIds().new_id()),
        BENCH,
        None,
        CategoryName("Their boards"),
        ManualClock().now(),
    )
    demo.catalog.categories.saved[theirs.id] = theirs
    their_part = PartDefinition.define(
        PartDefinitionId(NewIds().new_id()),
        theirs,
        PartDetails(PartName("Their board")),
        AttributeValues(),
        ManualClock().now(),
    )
    demo.catalog.parts.saved[their_part.id] = their_part

    await demo.restore(BENCH)

    assert "Their boards" not in demo.categories()
    assert "Their board" not in demo.parts()
    assert len(demo.categories()) == 3
    assert len(demo.parts()) == 5


async def test_restoring_twice_leaves_the_same_bench(demo: Demo) -> None:
    await demo.restore(BENCH)
    first = sorted(demo.parts())

    await demo.restore(BENCH)

    assert sorted(demo.parts()) == first
    assert len(demo.categories()) == 3


async def test_a_restore_is_one_commit_in_the_bench_it_was_asked_for(demo: Demo) -> None:
    await demo.restore(BENCH)

    assert demo.catalog.commits == 1
    assert demo.catalog.opened_for == [BENCH]


def test_every_sample_part_names_a_category_that_holds_it() -> None:
    """The data itself: a part hangs off the category whose schema it was written for."""
    assert [sample.name for sample in SAMPLE_CATALOG] == ["Passives"]
    [passives] = SAMPLE_CATALOG
    assert not passives.parts  # the root only carries the tolerance every passive has
    assert [child.name for child in passives.children] == ["Resistors", "Capacitors"]
    assert all(child.parts for child in passives.children)
