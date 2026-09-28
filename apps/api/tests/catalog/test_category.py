from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from uuid import uuid7

import pytest
from hypothesis import given
from hypothesis import strategies as st

from wiredex.catalog.domain.category import (
    MAX_CATEGORY_DEPTH,
    Category,
    CategoryPaths,
    check_depth,
    resolve_tracking_of,
)
from wiredex.catalog.domain.errors import (
    AmbiguousCategoryError,
    CategoryNotFoundError,
    CategoryTooDeepError,
    CircularCategoryError,
)
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


def tracked(name: str, value: bool | None, parent_id: CategoryId | None = None) -> Category:
    node = category(name, parent_id)
    node.tracked_individually = value
    return node


def test_setting_the_tracking_flag_reports_a_change() -> None:
    passives = category("Passives")

    assert passives.set_tracking(True)
    assert passives.tracked_individually is True


def test_setting_the_tracking_flag_to_what_it_already_is_changes_nothing() -> None:
    # The use case skips the commit on a False, as it does for a no-op rename.
    passives = tracked("Passives", True)

    assert not passives.set_tracking(True)


def test_clearing_the_tracking_flag_reports_a_change() -> None:
    passives = tracked("Passives", False)

    assert passives.set_tracking(None)
    assert passives.tracked_individually is None


def test_nothing_set_in_the_chain_resolves_to_lot_counted() -> None:
    # Requirement 6.2: the default when no ancestor and no category sets it is False.
    passives = category("Passives")
    resistors = category("Resistors", passives.id)

    assert resolve_tracking_of([passives, resistors]) is False


def test_an_ancestor_flag_is_inherited_down_the_chain() -> None:
    # Requirement 6.1: a category marked tracked passes it to its subcategories.
    passives = tracked("Passives", True)
    resistors = category("Resistors", passives.id)

    assert resolve_tracking_of([passives, resistors]) is True


def test_the_nearest_set_value_wins() -> None:
    # Requirement 6.2: a subcategory that sets the flag overrides an ancestor's.
    passives = tracked("Passives", True)
    resistors = tracked("Resistors", False, passives.id)
    thick_film = category("Thick film", resistors.id)

    assert resolve_tracking_of([passives, resistors, thick_film]) is False


def test_a_category_that_sets_the_flag_answers_with_its_own_value() -> None:
    boards = tracked("Boards", True)

    assert resolve_tracking_of([boards]) is True


# --- CategoryPaths: a category named by its path -----------------------------------------
#
# Passives → Resistors → Thick film, Passives → Capacitors, Legacy → Resistors, ICs → I/O
# expanders, and Resistências at the root: two Resistors to be ambiguous about, an accent to
# ignore, and a name holding the separator.

PASSIVES = category("Passives")
RESISTORS = category("Resistors", PASSIVES.id)
THICK_FILM = category("Thick film", RESISTORS.id)
CAPACITORS = category("Capacitors", PASSIVES.id)
LEGACY = category("Legacy")
OLD_RESISTORS = category("Resistors", LEGACY.id)
ICS = category("ICs")
EXPANDERS = category("I/O expanders", ICS.id)
RESISTENCIAS = category("Resistências")
TREE = [PASSIVES, RESISTORS, THICK_FILM, CAPACITORS, LEGACY, OLD_RESISTORS, ICS, EXPANDERS]


def paths() -> CategoryPaths:
    return CategoryPaths([*TREE, RESISTENCIAS])


def test_a_full_path_finds_its_category() -> None:
    assert paths().find("Passives / Resistors / Thick film") is THICK_FILM
    assert paths().find("Passives / Resistors") is RESISTORS


def test_the_tail_of_a_path_finds_its_category_when_no_other_path_ends_that_way() -> None:
    assert paths().find("Resistors / Thick film") is THICK_FILM


@pytest.mark.parametrize("name", ["Thick film", "Capacitors", "Legacy"])
def test_a_name_no_other_category_has_finds_it_alone(name: str) -> None:
    assert str(paths().find(name).name) == name


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        pytest.param("passives / resistors", RESISTORS, id="lower case"),
        pytest.param("PASSIVES/RESISTORS", RESISTORS, id="upper case, no spaces"),
        pytest.param("  Passives   /\tResistors  ", RESISTORS, id="spacing"),
        pytest.param("thick   FILM", THICK_FILM, id="inner spacing"),
        pytest.param("resistencias", RESISTENCIAS, id="accent dropped"),
        pytest.param("RESISTÊNCIAS", RESISTENCIAS, id="upper case, accent kept"),
        # Full-width, as a phone or a PDF copy types it.
        pytest.param("\uff52\uff45\uff53istencias", RESISTENCIAS, id="full-width letters"),
    ],
)
def test_a_path_is_found_whatever_its_case_accents_and_spacing(
    typed: str, expected: Category
) -> None:
    assert paths().find(typed) is expected


def test_a_path_two_categories_end_with_is_refused_naming_both() -> None:
    with pytest.raises(AmbiguousCategoryError) as refused:
        paths().find("resistors")

    assert "Legacy / Resistors or Passives / Resistors" in str(refused.value)
    # Typing more of the path is how the owner picks one.
    assert paths().find("Legacy / Resistors") is OLD_RESISTORS


def test_a_whole_path_wins_over_the_longer_paths_it_only_ends() -> None:
    # Otherwise the root Boards could never be named: its whole path is one name.
    boards = category("Boards")
    legacy = category("Legacy")
    old_boards = category("Boards", legacy.id)
    tree = CategoryPaths([boards, legacy, old_boards])

    assert tree.find("boards") is boards
    assert tree.find("Legacy / Boards") is old_boards


def test_siblings_whose_names_differ_only_in_case_are_ambiguous_even_by_full_path() -> None:
    # Case counts for a name (test above), so both can exist; folded, they read the same.
    upper = category("Passives")
    lower = category("passives")

    with pytest.raises(AmbiguousCategoryError, match="Passives or passives"):
        CategoryPaths([upper, lower]).find("Passives")


@pytest.mark.parametrize(
    "typed",
    [
        pytest.param("Inductors", id="no such name"),
        pytest.param("Passives / Thick film", id="a level skipped"),
        pytest.param("Resistors / Passives", id="the wrong way round"),
        pytest.param("Lab / Passives / Resistors", id="above the root"),
        pytest.param("Passives / / Resistors", id="an empty name"),
        pytest.param("", id="nothing"),
    ],
)
def test_a_path_no_category_ends_with_is_not_found(typed: str) -> None:
    with pytest.raises(CategoryNotFoundError, match="no category's path ends with"):
        paths().find(typed)


def test_a_refusal_quotes_the_path_as_typed_trimmed_and_spaced() -> None:
    with pytest.raises(CategoryNotFoundError, match="'passives / inductors'"):
        paths().find("  passives/inductors ")


def test_path_of_names_every_category_from_the_root_down() -> None:
    assert paths().path_of(THICK_FILM) == "Passives / Resistors / Thick film"
    assert paths().path_of(PASSIVES) == "Passives"


def test_every_path_path_of_prints_finds_its_category_again() -> None:
    # The preview shows `path_of`, so a sheet copied back from it still reads.
    tree = paths()

    for node in [*TREE, RESISTENCIAS]:
        assert tree.find(tree.path_of(node)) is node


@pytest.mark.parametrize("typed", ["ICs / I/O expanders", "I/O expanders", "i / o EXPANDERS"])
def test_a_name_holding_the_separator_is_found_by_its_pieces(typed: str) -> None:
    assert paths().find(typed) is EXPANDERS


def test_a_path_has_to_start_where_a_name_starts() -> None:
    # "O expanders" is the end of a name, not a name: finding it would be a guess.
    with pytest.raises(CategoryNotFoundError):
        paths().find("O expanders")


# --- Property 2: a path finds exactly the node it names ----------------------------------
#
# Trees come from a few names, so tails often end more than one path. Sibling names are
# distinct, which the catalog enforces up to case; the pool has no two names that differ
# only in case, whose full paths the test above shows are ambiguous by design.

_NAMES = ("Passives", "Resistors", "Thick film", "Capacitors", "Boards")
_CASES: tuple[Callable[[str], str], ...] = (str.upper, str.lower, str.swapcase, str.title)
_GAPS = st.text(alphabet=" \t\u00a0", max_size=3)


@st.composite
def category_trees(draw: st.DrawFn) -> list[tuple[int | None, str]]:
    """`(parent index, name)` pairs, parents first. Plain data: the test builds the nodes,
    so no strategy mints ids."""
    plan: list[tuple[int | None, str]] = []
    for _ in range(draw(st.integers(min_value=1, max_value=12))):
        parent = draw(st.none() | st.integers(0, len(plan) - 1)) if plan else None
        taken = {name for above, name in plan if above == parent}
        free = [name for name in _NAMES if name not in taken]
        if free:
            plan.append((parent, draw(st.sampled_from(free))))
    return plan


@st.composite
def typed_paths(draw: st.DrawFn, names: Sequence[str]) -> str:
    """The names joined by `/`, each in some case and with any spacing around and inside."""
    pieces = []
    for name in names:
        cased = draw(st.sampled_from(_CASES))(name)
        words = [
            word + draw(st.text(alphabet=" \t", min_size=1, max_size=2)) for word in cased.split()
        ]
        pieces.append(draw(_GAPS) + "".join(words) + draw(_GAPS))
    return "/".join(pieces)


@given(plan=category_trees(), data=st.data())
def test_a_path_finds_exactly_the_category_it_names(
    plan: list[tuple[int | None, str]], data: st.DataObject
) -> None:
    """Property 2: a path or a code finds exactly the node it names (the category half).

    A category's full path, in any case and spacing, finds it. A tail of its path finds the
    category whose whole path it is, when there is one; else it finds this category exactly
    when no other category's path ends with the same names, and is otherwise refused as
    ambiguous, naming every category it could be.

    **Validates: Requirements 5.4**
    """
    nodes: list[Category] = []
    chains: list[list[str]] = []
    for parent, name in plan:
        nodes.append(category(name, None if parent is None else nodes[parent].id))
        chains.append([*([] if parent is None else chains[parent]), name])
    tree = CategoryPaths(nodes)
    index = data.draw(st.integers(0, len(nodes) - 1), label="category")
    chain = chains[index]
    tail = chain[-data.draw(st.integers(1, len(chain)), label="tail length") :]

    assert tree.find(data.draw(typed_paths(chain), label="full path")) is nodes[index]

    typed = data.draw(typed_paths(tail), label="tail")
    whole = [other for other, names in enumerate(chains) if names == tail]
    ending = [other for other, names in enumerate(chains) if names[-len(tail) :] == tail]
    candidates = whole or ending
    if len(candidates) == 1:
        assert tree.find(typed) is nodes[candidates[0]]
    else:
        with pytest.raises(AmbiguousCategoryError) as refused:
            tree.find(typed)
        paths = sorted(" / ".join(chains[other]) for other in candidates)
        assert " or ".join(paths) in str(refused.value)
