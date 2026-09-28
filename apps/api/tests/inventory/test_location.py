from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from uuid import uuid7

import pytest
from hypothesis import given
from hypothesis import strategies as st

from wiredex.inventory.domain.errors import (
    AmbiguousLocationError,
    CircularLocationError,
    LocationNotFoundError,
)
from wiredex.inventory.domain.location import (
    MAX_LOCATION_DEPTH,
    Location,
    LocationPaths,
    LocationTooDeepError,
    check_depth,
)
from wiredex.inventory.domain.values import (
    LocationId,
    LocationName,
    ShortCode,
    WorkspaceId,
)

NOW = datetime(2026, 9, 26, 10, 0, tzinfo=UTC)
BENCH = WorkspaceId(uuid7())

_next_code = iter(range(1, 10_000))


def location(name: str, parent_id: LocationId | None = None) -> Location:
    code = ShortCode.for_location(next(_next_code))
    return Location(LocationId(uuid7()), BENCH, parent_id, code, LocationName(name), NOW)


def a_chain(length: int) -> list[LocationId]:
    """`length` ancestors above a location, which is all the depth rule reads of them."""
    return [LocationId(uuid7()) for _ in range(length)]


def test_renaming_a_location_reports_that_something_changed() -> None:
    drawer = location("Drawer 3")

    assert drawer.rename(LocationName("Drawer 4"))
    assert str(drawer.name) == "Drawer 4"


def test_renaming_a_location_to_the_name_it_already_has_changes_nothing() -> None:
    # Requirement 1.9: the use case skips the commit on a False.
    drawer = location("Drawer 3")

    assert not drawer.rename(LocationName("  Drawer 3  "))
    assert str(drawer.name) == "Drawer 3"


def test_a_difference_in_case_is_a_real_rename() -> None:
    # Case is the owner's choice, so *lab* is a different name from *Lab*.
    lab = location("Lab")

    assert lab.rename(LocationName("lab"))


def test_renaming_a_location_leaves_its_short_code_unchanged() -> None:
    # Requirement 1.8: the code is assigned once and a rename never touches it.
    drawer = location("Drawer 3")
    code = drawer.code

    drawer.rename(LocationName("Drawer 4"))

    assert drawer.code == code


def test_a_location_moves_under_a_parent() -> None:
    lab = location("Lab")
    drawer = location("Drawer 3")

    drawer.move_under(lab, [])

    assert drawer.parent_id == lab.id


def test_a_location_moves_back_to_the_root() -> None:
    lab = location("Lab")
    drawer = location("Drawer 3", lab.id)

    drawer.move_under(None, [])

    assert drawer.parent_id is None


def test_moving_a_location_leaves_its_short_code_unchanged() -> None:
    # Requirement 1.8: a move never touches the code either.
    lab = location("Lab")
    drawer = location("Drawer 3")
    code = drawer.code

    drawer.move_under(lab, [])

    assert drawer.code == code


def test_a_location_cannot_move_under_itself() -> None:
    lab = location("Lab")

    with pytest.raises(CircularLocationError, match="Lab"):
        lab.move_under(lab, [])

    assert lab.parent_id is None


def test_a_location_cannot_move_under_one_of_its_own_descendants() -> None:
    # Requirement 1.5. Lab → Cabinet → Drawer 3, then Lab under Drawer 3: the use case reads
    # Drawer 3's chain, and Lab is in it.
    lab = location("Lab")
    cabinet = location("Cabinet", lab.id)
    drawer = location("Drawer 3", cabinet.id)

    with pytest.raises(CircularLocationError):
        lab.move_under(drawer, [lab.id, cabinet.id])

    assert lab.parent_id is None


def test_a_location_cannot_move_under_a_parent_that_sits_at_the_cap() -> None:
    deepest = location("Bin")
    stranded = location("Spare")

    with pytest.raises(LocationTooDeepError, match=f"deeper than {MAX_LOCATION_DEPTH} levels"):
        stranded.move_under(deepest, a_chain(MAX_LOCATION_DEPTH - 1))

    assert stranded.parent_id is None


def test_the_last_allowed_level_is_still_allowed() -> None:
    parent = location("Bin")
    leaf = location("Spare")

    # Four ancestors above the parent puts the parent at 5 and the leaf at the sixth level.
    leaf.move_under(parent, a_chain(MAX_LOCATION_DEPTH - 2))

    assert leaf.parent_id == parent.id


@pytest.mark.parametrize(
    ("above", "below"),
    [
        pytest.param(MAX_LOCATION_DEPTH - 1, 0, id="a location at the cap"),
        pytest.param(0, MAX_LOCATION_DEPTH - 1, id="a subtree reaching the cap"),
    ],
)
def test_the_cap_counts_the_location_itself_and_the_levels_under_it(above: int, below: int) -> None:
    check_depth(a_chain(above), below)

    with pytest.raises(LocationTooDeepError, match=f"would reach {MAX_LOCATION_DEPTH + 1}"):
        check_depth(a_chain(above + 1), below)


def test_a_root_location_is_the_first_level() -> None:
    # Requirement 1.4 counts levels, not parents: a root is 1 of the 6.
    check_depth([])


# --- LocationPaths: a location named by its short code or its path -----------------------
#
# Lab → Cabinet A → Drawer 3, Lab → Cabinet B → Drawer 3, Lab → In/out tray, a root Bench
# beside Lab → Bench, and Gaveta três at the root: two Drawer 3 to be ambiguous about, a
# whole path to win over a tail, an accent to ignore, and a name holding the separator.


def placed(name: str, number: int, parent: Location | None = None) -> Location:
    """A location with the code its number mints, so a test can type it."""
    parent_id = None if parent is None else parent.id
    code = ShortCode.for_location(number)
    return Location(LocationId(uuid7()), BENCH, parent_id, code, LocationName(name), NOW)


LAB = placed("Lab", 1)
CABINET_A = placed("Cabinet A", 2, LAB)
DRAWER_A = placed("Drawer 3", 3, CABINET_A)
CABINET_B = placed("Cabinet B", 4, LAB)
DRAWER_B = placed("Drawer 3", 5, CABINET_B)
TRAY = placed("In/out tray", 6, LAB)
ROOT_BENCH = placed("Bench", 7)
LAB_BENCH = placed("Bench", 8, LAB)
GAVETA = placed("Gaveta três", 9)
PLACES = [LAB, CABINET_A, DRAWER_A, CABINET_B, DRAWER_B, TRAY, ROOT_BENCH, LAB_BENCH, GAVETA]


def paths() -> LocationPaths:
    return LocationPaths(PLACES)


@pytest.mark.parametrize("typed", ["WX-L-0003", "wx-l-0003", "  Wx-L-0003\t"])
def test_a_short_code_finds_its_location_in_any_case(typed: str) -> None:
    assert paths().find(typed) is DRAWER_A


def test_a_short_code_finds_a_location_its_name_alone_cant() -> None:
    # Drawer 3 is ambiguous by name; its code never is.
    assert paths().find("WX-L-0005") is DRAWER_B


def test_a_short_code_no_location_holds_is_not_found() -> None:
    with pytest.raises(LocationNotFoundError, match="'WX-L-0999' is neither a location's"):
        paths().find("WX-L-0999")


def test_text_shaped_like_a_code_no_location_holds_is_still_a_path() -> None:
    # A location's name is free text, so a code nobody holds may still be one.
    odd = placed("WX-L-0042", 10)

    assert LocationPaths([*PLACES, odd]).find("wx-l-0042") is odd


def test_a_code_wins_over_a_name_spelled_like_it() -> None:
    impostor = placed("WX-L-0003", 11)

    assert LocationPaths([*PLACES, impostor]).find("WX-L-0003") is DRAWER_A


def test_a_full_path_finds_its_location() -> None:
    assert paths().find("Lab / Cabinet A / Drawer 3") is DRAWER_A
    assert paths().find("Lab / Cabinet B") is CABINET_B


def test_the_tail_of_a_path_finds_its_location_when_no_other_path_ends_that_way() -> None:
    assert paths().find("Cabinet B / Drawer 3") is DRAWER_B


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        pytest.param("lab/cabinet a/DRAWER 3", DRAWER_A, id="case, no spaces"),
        pytest.param("  Cabinet   B /\tDrawer 3 ", DRAWER_B, id="spacing"),
        pytest.param("gaveta tres", GAVETA, id="accent dropped"),
        pytest.param("GAVETA TRÊS", GAVETA, id="upper case, accent kept"),
    ],
)
def test_a_path_is_found_whatever_its_case_accents_and_spacing(
    typed: str, expected: Location
) -> None:
    assert paths().find(typed) is expected


def test_a_path_two_locations_end_with_is_refused_naming_both() -> None:
    with pytest.raises(AmbiguousLocationError) as refused:
        paths().find("drawer 3")

    message = str(refused.value)
    assert "Lab / Cabinet A / Drawer 3 or Lab / Cabinet B / Drawer 3" in message
    assert "short code" in message


def test_a_whole_path_wins_over_the_longer_paths_it_only_ends() -> None:
    # Otherwise the root Bench could never be named: its whole path is one name.
    assert paths().find("bench") is ROOT_BENCH
    assert paths().find("Lab / Bench") is LAB_BENCH


@pytest.mark.parametrize(
    "typed",
    [
        pytest.param("Cabinet C", id="no such name"),
        pytest.param("Lab / Drawer 3", id="a level skipped"),
        pytest.param("Drawer 3 / Cabinet A", id="the wrong way round"),
        pytest.param("", id="nothing"),
    ],
)
def test_a_path_no_location_ends_with_is_not_found(typed: str) -> None:
    with pytest.raises(LocationNotFoundError, match="neither a location's short code"):
        paths().find(typed)


@pytest.mark.parametrize("typed", ["Lab / In/out tray", "In/out tray", "in / OUT tray"])
def test_a_name_holding_the_separator_is_found_by_its_pieces(typed: str) -> None:
    assert paths().find(typed) is TRAY


def test_a_path_has_to_start_where_a_name_starts() -> None:
    with pytest.raises(LocationNotFoundError):
        paths().find("out tray")


def test_path_of_names_every_location_from_the_root_down() -> None:
    assert paths().path_of(DRAWER_A) == "Lab / Cabinet A / Drawer 3"
    assert paths().path_of(LAB) == "Lab"


def test_every_path_path_of_prints_finds_its_location_again() -> None:
    # The preview shows `path_of`, so a sheet copied back from it still reads.
    tree = paths()

    for node in PLACES:
        assert tree.find(tree.path_of(node)) is node


# --- Property 2: a path or a code finds exactly the node it names -------------------------
#
# Trees come from a few names, so tails often end more than one path. Sibling names differ
# once folded: the pool has no two names that differ only in case or accents.

_NAMES = ("Lab", "Cabinet A", "Drawer 3", "Bin", "Gaveta três")
_CASES: tuple[Callable[[str], str], ...] = (str.upper, str.lower, str.swapcase, str.title)
_GAPS = st.text(alphabet=" \t\u00a0", max_size=3)


@st.composite
def location_trees(draw: st.DrawFn) -> list[tuple[int | None, str]]:
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


@given(plan=location_trees(), data=st.data())
def test_a_path_or_a_code_finds_exactly_the_location_it_names(
    plan: list[tuple[int | None, str]], data: st.DataObject
) -> None:
    """Property 2: a path or a code finds exactly the node it names (the location half).

    A location's full path, in any case and spacing, finds it. A tail of its path finds the
    location whose whole path it is, when there is one; else it finds this location exactly
    when no other location's path ends with the same names, and is otherwise refused as
    ambiguous, naming every location it could be. Its short code, in any case, finds it.

    **Validates: Requirements 6.5**
    """
    nodes: list[Location] = []
    chains: list[list[str]] = []
    for number, (parent, name) in enumerate(plan, start=1):
        nodes.append(placed(name, number, None if parent is None else nodes[parent]))
        chains.append([*([] if parent is None else chains[parent]), name])
    tree = LocationPaths(nodes)
    index = data.draw(st.integers(0, len(nodes) - 1), label="location")
    chain = chains[index]
    tail = chain[-data.draw(st.integers(1, len(chain)), label="tail length") :]

    assert tree.find(data.draw(typed_paths(chain), label="full path")) is nodes[index]

    code = data.draw(st.sampled_from(_CASES), label="code case")(str(nodes[index].code))
    assert tree.find(data.draw(_GAPS) + code + data.draw(_GAPS)) is nodes[index]

    typed = data.draw(typed_paths(tail), label="tail")
    whole = [other for other, names in enumerate(chains) if names == tail]
    ending = [other for other, names in enumerate(chains) if names[-len(tail) :] == tail]
    candidates = whole or ending
    if len(candidates) == 1:
        assert tree.find(typed) is nodes[candidates[0]]
    else:
        with pytest.raises(AmbiguousLocationError) as refused:
            tree.find(typed)
        found = sorted(" / ".join(chains[other]) for other in candidates)
        assert " or ".join(found) in str(refused.value)
