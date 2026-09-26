from datetime import UTC, datetime
from uuid import uuid7

import pytest

from wiredex.inventory.domain.errors import CircularLocationError
from wiredex.inventory.domain.location import (
    MAX_LOCATION_DEPTH,
    Location,
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
