"""The category use cases over the in-memory catalog: the tree rules, end to end.

Every refusal also asserts that nothing was committed, because "reject it and leave the
tree unchanged" is half of what requirements 1.3, 1.5, 1.6 and 1.9 ask for.
"""

from uuid import uuid7

import pytest

from support.catalog import BENCH, World
from wiredex.catalog.application.categories import NewCategory
from wiredex.catalog.domain.category import MAX_CATEGORY_DEPTH, Category
from wiredex.catalog.domain.errors import (
    CategoryInUseError,
    CategoryNotFoundError,
    CategoryTooDeepError,
    CircularCategoryError,
    DuplicateCategoryNameError,
)
from wiredex.catalog.domain.values import CategoryId, CategoryName

pytestmark = pytest.mark.anyio


def chain(world: World, levels: int) -> Category:
    """`levels` categories, each under the last, the first at the root. Returns the deepest."""
    deepest = world.add_category("Level 1")
    for level in range(2, levels + 1):
        deepest = world.add_category(f"Level {level}", deepest)
    return deepest


async def test_a_category_with_no_parent_becomes_a_root_of_the_callers_bench() -> None:
    world = World()

    capacitors = await world.create_category(BENCH, NewCategory(CategoryName("Capacitors")))

    assert capacitors.parent_id is None
    assert capacitors.workspace_id == BENCH
    assert world.catalog.categories.saved[capacitors.id] is capacitors
    assert world.catalog.commits == 1
    # The unit of work was opened for the caller's workspace and no other (requirement 6.1).
    assert world.catalog.opened_for == [BENCH]


async def test_a_category_with_a_parent_lands_under_it() -> None:
    world = World()

    thick_film = await world.create_category(
        BENCH, NewCategory(CategoryName("Thick film"), world.resistors.id)
    )

    assert thick_film.parent_id == world.resistors.id


async def test_two_siblings_cannot_share_a_name_and_two_roots_are_siblings() -> None:
    world = World()

    with pytest.raises(DuplicateCategoryNameError, match="Resistors"):
        await world.create_category(
            BENCH, NewCategory(CategoryName("Resistors"), world.passives.id)
        )
    # Requirement 1.3's tail: the table spells this NULLS NOT DISTINCT, the use case
    # spells it "a root has the other roots for siblings".
    with pytest.raises(DuplicateCategoryNameError, match="Passives"):
        await world.create_category(BENCH, NewCategory(CategoryName("Passives")))

    assert len(world.catalog.categories.saved) == 2
    assert world.catalog.commits == 0


async def test_a_category_cannot_be_created_deeper_than_the_cap() -> None:
    world = World()
    deepest = chain(world, MAX_CATEGORY_DEPTH)

    with pytest.raises(CategoryTooDeepError, match=f"reach {MAX_CATEGORY_DEPTH + 1}"):
        await world.create_category(BENCH, NewCategory(CategoryName("Anti-surge"), deepest.id))

    assert world.catalog.commits == 0


async def test_an_unknown_parent_is_simply_not_found() -> None:
    world = World()

    with pytest.raises(CategoryNotFoundError):
        await world.create_category(BENCH, NewCategory(CategoryName("Orphan"), CategoryId(uuid7())))

    assert world.catalog.commits == 0


async def test_renaming_a_category_commits_the_new_name() -> None:
    world = World()

    renamed = await world.rename_category(
        BENCH, world.resistors.id, CategoryName("Fixed resistors")
    )

    assert str(renamed.name) == "Fixed resistors"
    assert world.catalog.commits == 1


async def test_renaming_a_category_to_the_name_it_already_has_commits_nothing() -> None:
    # Requirement 1.8, and the reason the entity's mutators return whether they changed.
    world = World()

    renamed = await world.rename_category(BENCH, world.passives.id, CategoryName("  Passives  "))

    assert str(renamed.name) == "Passives"
    assert world.catalog.commits == 0


async def test_a_rename_onto_a_siblings_name_is_refused() -> None:
    world = World()
    world.add_category("Capacitors")

    with pytest.raises(DuplicateCategoryNameError, match="Capacitors"):
        await world.rename_category(BENCH, world.passives.id, CategoryName("Capacitors"))

    assert str(world.passives.name) == "Passives"
    assert world.catalog.commits == 0


async def test_a_category_moves_under_another_parent_and_back_to_the_root() -> None:
    world = World()
    capacitors = world.add_category("Capacitors")

    moved = await world.move_category(BENCH, world.resistors.id, capacitors.id)
    assert moved.parent_id == capacitors.id

    rooted = await world.move_category(BENCH, world.resistors.id, None)
    assert rooted.parent_id is None
    assert world.catalog.commits == 2


async def test_a_category_cannot_move_under_one_of_its_own_descendants() -> None:
    # Requirement 1.5: the use case reads Thick film's chain and Passives is in it.
    world = World()
    thick_film = world.add_category("Thick film", world.resistors)

    with pytest.raises(CircularCategoryError):
        await world.move_category(BENCH, world.passives.id, thick_film.id)

    assert world.passives.parent_id is None
    assert world.catalog.commits == 0


async def test_a_move_counts_the_levels_riding_along_under_the_category() -> None:
    # Requirement 1.6. Passives alone would fit as the sixth level; Resistors under it
    # would be the seventh, which only a reader of the tree can see.
    world = World()
    fifth = chain(world, MAX_CATEGORY_DEPTH - 1)

    with pytest.raises(CategoryTooDeepError, match=f"reach {MAX_CATEGORY_DEPTH + 1}"):
        await world.move_category(BENCH, world.passives.id, fifth.id)

    assert world.passives.parent_id is None
    assert world.catalog.commits == 0


async def test_a_subtree_that_still_fits_under_the_cap_moves() -> None:
    world = World()
    fourth = chain(world, MAX_CATEGORY_DEPTH - 2)

    moved = await world.move_category(BENCH, world.passives.id, fourth.id)

    assert moved.parent_id == fourth.id
    assert world.catalog.commits == 1


async def test_a_move_into_a_parent_that_already_has_that_name_is_refused() -> None:
    world = World()
    rogue = world.add_category("Resistors")

    with pytest.raises(DuplicateCategoryNameError, match="Resistors"):
        await world.move_category(BENCH, rogue.id, world.passives.id)

    assert rogue.parent_id is None
    assert world.catalog.commits == 0


async def test_a_category_with_children_is_not_deleted() -> None:
    world = World()

    with pytest.raises(CategoryInUseError, match="categories under it"):
        await world.delete_category(BENCH, world.passives.id)

    assert len(world.catalog.categories.saved) == 2
    assert world.catalog.commits == 0


async def test_a_category_with_parts_is_not_deleted() -> None:
    world = World()
    world.add_part(world.resistors)

    with pytest.raises(CategoryInUseError, match="still has parts"):
        await world.delete_category(BENCH, world.resistors.id)

    assert world.resistors.id in world.catalog.categories.saved
    assert world.catalog.commits == 0


async def test_deleting_a_category_takes_its_own_attribute_definitions_with_it() -> None:
    # Requirement 1.10. Passives stays: a delete is one category, never a cascade up.
    world = World()

    await world.delete_category(BENCH, world.resistors.id)

    assert world.resistors.id not in world.catalog.categories.saved
    assert world.catalog.attribute_definitions.saved == {}
    assert world.passives.id in world.catalog.categories.saved
    assert world.catalog.commits == 1


async def test_the_tree_reports_each_categorys_children_and_parts() -> None:
    # Requirement 1.11, and the counts the web needs to grey out a delete button.
    world = World()
    world.add_part(world.resistors)
    world.add_part(world.resistors, "R 10k 0805")

    nodes = await world.list_categories(BENCH)

    assert [(str(n.category.name), n.child_count, n.part_count) for n in nodes] == [
        ("Passives", 1, 0),
        ("Resistors", 0, 2),
    ]
    assert world.catalog.commits == 0
