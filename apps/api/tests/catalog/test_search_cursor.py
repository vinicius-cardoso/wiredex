"""The sort and the opaque cursor: how a page is ordered, and how the next one continues.

`PartSort` refuses a shape that contradicts itself (an attribute sort with no key, a name
sort carrying one). `SearchCursor` round-trips through its base64url token and refuses two
things: a token that doesn't decode, and a cursor made for a different search — the
fingerprint is what a cursor belongs to (requirement 4.4). Property 3 is the last test.
"""

import base64
import json
from uuid import uuid7

import pytest
from hypothesis import given
from hypothesis import strategies as st

from wiredex.catalog.domain.errors import InvalidCursorError, InvalidSortError
from wiredex.catalog.domain.search import (
    PartSort,
    SearchCursor,
    SortDirection,
    SortField,
)
from wiredex.catalog.domain.values import AttributeKey, PartDefinitionId

RESISTANCE = AttributeKey("resistance")
FINGERPRINT = "9c1e4b7a2f0d"


def a_cursor(
    *,
    sort: PartSort | None = None,
    last_value: str | None = "4700",
    fingerprint: str = FINGERPRINT,
) -> SearchCursor:
    return SearchCursor(
        sort or PartSort.by_attribute(RESISTANCE, SortDirection.ASC),
        last_value,
        PartDefinitionId(uuid7()),
        fingerprint,
    )


# --- PartSort --------------------------------------------------------------------------


def test_part_sort_defaults_to_newest_descending() -> None:
    sort = PartSort.newest()

    assert sort.field is SortField.NEWEST
    assert sort.direction is SortDirection.DESC
    assert sort.key is None
    assert sort.token == "newest"


def test_part_sort_by_name_defaults_to_ascending() -> None:
    sort = PartSort.by_name()

    assert sort.field is SortField.NAME
    assert sort.direction is SortDirection.ASC
    assert sort.token == "name"


def test_part_sort_by_attribute_carries_the_key_in_its_token() -> None:
    sort = PartSort.by_attribute(RESISTANCE, SortDirection.DESC)

    assert sort.field is SortField.ATTRIBUTE
    assert sort.key == RESISTANCE
    assert sort.token == "attribute:resistance"


def test_part_sort_refuses_an_attribute_sort_without_a_key() -> None:
    with pytest.raises(InvalidSortError):
        PartSort(SortField.ATTRIBUTE)


@pytest.mark.parametrize("field", [SortField.NEWEST, SortField.NAME])
def test_part_sort_refuses_a_non_attribute_sort_carrying_a_key(field: SortField) -> None:
    with pytest.raises(InvalidSortError):
        PartSort(field, key=RESISTANCE)


# --- SearchCursor round trip -----------------------------------------------------------


@pytest.mark.parametrize(
    "sort",
    [
        PartSort.newest(),
        PartSort.by_name(SortDirection.DESC),
        PartSort.by_attribute(RESISTANCE, SortDirection.ASC),
    ],
)
def test_a_cursor_round_trips_through_its_token(sort: PartSort) -> None:
    original = a_cursor(sort=sort)

    restored = SearchCursor.decode(original.encode(), FINGERPRINT)

    assert restored == original


def test_a_cursor_round_trips_a_missing_sort_value() -> None:
    # A part without the sort attribute sorts last and carries no value across the cursor.
    original = a_cursor(last_value=None)

    restored = SearchCursor.decode(original.encode(), FINGERPRINT)

    assert restored.last_value is None
    assert restored == original


# --- SearchCursor refusals -------------------------------------------------------------


@pytest.mark.parametrize(
    "token",
    [
        "",
        "not base64!",
        "@@@@",
        base64.urlsafe_b64encode(b"not json at all").decode(),
        base64.urlsafe_b64encode(b"[1, 2, 3]").decode(),  # decodes, but not an object
        base64.urlsafe_b64encode(json.dumps({"s": "newest"}).encode()).decode(),  # missing fields
    ],
)
def test_garbage_is_refused(token: str) -> None:
    with pytest.raises(InvalidCursorError):
        SearchCursor.decode(token, FINGERPRINT)


def test_a_cursor_with_an_id_that_isnt_a_uuid_is_refused() -> None:
    payload = {"s": "newest", "d": "desc", "v": "4700", "i": "not-a-uuid", "f": FINGERPRINT}
    token = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()

    with pytest.raises(InvalidCursorError):
        SearchCursor.decode(token, FINGERPRINT)


def test_a_cursor_with_an_unknown_sort_is_refused() -> None:
    payload = {"s": "oldest", "d": "desc", "v": None, "i": str(uuid7()), "f": FINGERPRINT}
    token = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()

    with pytest.raises(InvalidCursorError):
        SearchCursor.decode(token, FINGERPRINT)


def test_a_cursor_with_an_unknown_direction_is_refused() -> None:
    payload = {"s": "newest", "d": "sideways", "v": None, "i": str(uuid7()), "f": FINGERPRINT}
    token = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()

    with pytest.raises(InvalidCursorError):
        SearchCursor.decode(token, FINGERPRINT)


def test_a_cursor_from_another_search_is_refused() -> None:
    # The token decodes cleanly; it is refused only because its fingerprint is another search's.
    token = a_cursor(fingerprint="a-different-search").encode()

    with pytest.raises(InvalidCursorError):
        SearchCursor.decode(token, FINGERPRINT)


# --- Property 3: a cursor belongs to its search ----------------------------------------
#
# A search is represented here by its fingerprint, the hash the application (task 3) makes
# of the normalized search: two searches that differ in any field hash to different strings,
# and the same search always to the same one. So the property over cursors is exactly this —
# a cursor decodes under its own fingerprint and is refused under any other.

_FINGERPRINTS = st.text(min_size=1, max_size=64)


@given(
    made_for=_FINGERPRINTS,
    replayed_against=_FINGERPRINTS,
    last_value=st.none() | st.text(max_size=32),
    # Any UUID: the cursor round-trips the id, it never reads its version.
    part_id=st.uuids(),
)
def test_a_cursor_belongs_to_its_search(
    made_for: str, replayed_against: str, last_value: str | None, part_id: object
) -> None:
    """Validates: Requirements 4.4"""
    cursor = SearchCursor(
        PartSort.by_attribute(RESISTANCE, SortDirection.ASC),
        last_value,
        PartDefinitionId(part_id),  # type: ignore[arg-type]
        made_for,
    )
    token = cursor.encode()

    # Accepted by the search it was made for: it decodes back to the same cursor.
    assert SearchCursor.decode(token, made_for) == cursor

    # Refused by any search whose fingerprint differs.
    if replayed_against != made_for:
        with pytest.raises(InvalidCursorError):
            SearchCursor.decode(token, replayed_against)
