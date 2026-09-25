from datetime import UTC, datetime
from uuid import uuid7

import pytest

from wiredex.catalog.domain.category import MAX_CATEGORY_DEPTH, Category, check_depth
from wiredex.catalog.domain.errors import CategoryTooDeepError, CircularCategoryError
from wiredex.catalog.domain.values import CategoryId, CategoryName, WorkspaceId

NOW = datetime(2026, 9, 25, 10, 0, tzinfo=UTC)
BENCH = WorkspaceId(uuid7())


def category(name: str, parent_id: CategoryId | None = None) -> Category:
    return Category(CategoryId(uuid7()), BENCH, parent_id, CategoryName(name), NOW)


def a_chain(length: int) -> list[CategoryId]:
    """`length` ancestors above a category, which is all the depth rule reads of them."""
    return [CategoryId(uuid7()) for _ in range(length)]


def test_renaming_a_category_reports_that_something_changed() -> None:
    passives = category("Passives")

    assert passives.rename(CategoryName("Discrete passives"))
    assert str(passives.name) == "Discrete passives"


def test_renaming_a_category_to_the_name_it_already_has_changes_nothing() -> None:
    # Requirement 1.8: the use case skips the commit on a False.
    passives = category("Passives")

    assert not passives.rename(CategoryName("  Passives  "))
    assert str(passives.name) == "Passives"


def test_a_difference_in_case_is_a_real_rename() -> None:
    # Case is the owner's choice, so *passives* is a different name from *Passives*.
    passives = category("Passives")

    assert passives.rename(CategoryName("passives"))


def test_a_category_moves_under_a_parent() -> None:
    passives = category("Passives")
    resistors = category("Resistors")

    resistors.move_under(passives, [])

    assert resistors.parent_id == passives.id


def test_a_category_moves_back_to_the_root() -> None:
    passives = category("Passives")
    resistors = category("Resistors", passives.id)

    resistors.move_under(None, [])

    assert resistors.parent_id is None


def test_a_category_cannot_move_under_itself() -> None:
    passives = category("Passives")

    with pytest.raises(CircularCategoryError, match="Passives"):
        passives.move_under(passives, [])

    assert passives.parent_id is None


def test_a_category_cannot_move_under_one_of_its_own_descendants() -> None:
    # Requirement 1.5. Passives → Resistors → Thick film, then Passives under Thick film:
    # the use case reads Thick film's chain, and Passives is in it.
    passives = category("Passives")
    resistors = category("Resistors", passives.id)
    thick_film = category("Thick film", resistors.id)

    with pytest.raises(CircularCategoryError):
        passives.move_under(thick_film, [passives.id, resistors.id])

    assert passives.parent_id is None


def test_a_category_cannot_move_under_a_parent_that_sits_at_the_cap() -> None:
    deepest = category("Thick film")
    stranded = category("Anti-surge")

    with pytest.raises(CategoryTooDeepError, match=f"deeper than {MAX_CATEGORY_DEPTH} levels"):
        stranded.move_under(deepest, a_chain(MAX_CATEGORY_DEPTH - 1))

    assert stranded.parent_id is None


def test_the_last_allowed_level_is_still_allowed() -> None:
    parent = category("Thick film")
    leaf = category("Anti-surge")

    # Four ancestors above the parent puts the parent at 5 and the leaf at the sixth level.
    leaf.move_under(parent, a_chain(MAX_CATEGORY_DEPTH - 2))

    assert leaf.parent_id == parent.id


@pytest.mark.parametrize(
    ("above", "below"),
    [
        pytest.param(MAX_CATEGORY_DEPTH - 1, 0, id="a category at the cap"),
        pytest.param(0, MAX_CATEGORY_DEPTH - 1, id="a subtree reaching the cap"),
    ],
)
def test_the_cap_counts_the_category_itself_and_the_levels_under_it(above: int, below: int) -> None:
    check_depth(a_chain(above), below)

    with pytest.raises(CategoryTooDeepError, match=f"would reach {MAX_CATEGORY_DEPTH + 1}"):
        check_depth(a_chain(above + 1), below)


def test_a_root_category_is_the_first_level() -> None:
    # Requirement 1.4 counts levels, not parents: a root is 1 of the 6.
    check_depth([])
