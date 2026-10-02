"""The search's domain: the text it takes, and how a kind's hits become a group.

Property 1 lives here (19-command-palette, Correctness Properties).
"""

from uuid import uuid7

import pytest
from hypothesis import given
from hypothesis import strategies as st

from wiredex.search.domain.errors import InvalidSearchError
from wiredex.search.domain.search import (
    MAX_LIMIT,
    MAX_TEXT_LENGTH,
    SearchGroup,
    SearchHit,
    SearchKind,
    SearchText,
    group,
    results,
)


def hits(kind: SearchKind, count: int) -> list[SearchHit]:
    return [SearchHit(kind, uuid7(), f"{kind} {index}", None) for index in range(count)]


class TestSearchText:
    def test_is_trimmed(self) -> None:
        assert SearchText.of("  4k7 ").value == "4k7"

    @pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
    def test_a_blank_text_is_refused(self, blank: str) -> None:
        # Requirement 1.5.
        with pytest.raises(InvalidSearchError, match="type something"):
            SearchText.of(blank)

    def test_takes_up_to_100_characters_once_trimmed(self) -> None:
        assert SearchText.of(f" {'x' * MAX_TEXT_LENGTH} ").value == "x" * MAX_TEXT_LENGTH
        with pytest.raises(InvalidSearchError, match="at most 100"):
            SearchText.of("x" * (MAX_TEXT_LENGTH + 1))


class TestGroups:
    def test_a_kind_that_found_nothing_has_no_group(self) -> None:
        assert group(SearchKind.PART, [], 5) is None

    def test_the_groups_follow_the_kinds_order_whatever_order_they_came_in(self) -> None:
        # Requirement 1.3: parts, units, projects, firmware, categories, locations.
        found = [
            group(SearchKind.LOCATION, hits(SearchKind.LOCATION, 1), 5),
            group(SearchKind.UNIT, [], 5),
            group(SearchKind.PART, hits(SearchKind.PART, 2), 5),
            group(SearchKind.CATEGORY, hits(SearchKind.CATEGORY, 1), 5),
        ]

        answered = results(SearchText.of(" sensor "), found)

        assert answered.text == "sensor"
        assert [one.kind for one in answered.groups] == [
            SearchKind.PART,
            SearchKind.CATEGORY,
            SearchKind.LOCATION,
        ]


class TestProperty1:
    @given(
        matching=st.integers(min_value=0, max_value=MAX_LIMIT + 3),
        limit=st.integers(min_value=1, max_value=MAX_LIMIT),
    )
    def test_a_group_shows_at_most_its_limit_and_says_when_more_match(
        self, matching: int, limit: int
    ) -> None:
        """For any number of matches a source holds, asked for `limit + 1` of them, the group
        holds the first `min(n, limit)` in the source's order, `more` exactly when `n > limit`,
        and a kind with no match has no group.

        **Validates: 19-command-palette Requirements 1.3, 1.4**
        """
        held = hits(SearchKind.PART, matching)
        asked = held[: limit + 1]

        found = group(SearchKind.PART, asked, limit)

        if matching == 0:
            assert found is None
        else:
            assert found == SearchGroup(
                SearchKind.PART, tuple(held[: min(matching, limit)]), more=matching > limit
            )
