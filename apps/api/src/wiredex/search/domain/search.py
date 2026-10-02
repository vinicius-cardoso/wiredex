"""The workspace searched as one list: six kinds of record, each a group of the closest hits.

Each kind's module finds its own records and orders them (19-command-palette, decisions 1 and
2); this file is what makes one answer of the six. A kind is asked for one more hit than a group
shows, so the group can say whether more match without counting them (decision 3).
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from wiredex.search.domain.errors import InvalidSearchError

# How many hits a group shows: five unless asked, never more than 20 (requirement 1.4).
DEFAULT_LIMIT = 5
MAX_LIMIT = 20
# The longest text a search takes, past which it is refused (requirement 1.5).
MAX_TEXT_LENGTH = 100


class SearchKind(StrEnum):
    """What a hit is, and which module finds it. The members' order is the groups' order
    (requirement 1.3)."""

    PART = "part"
    UNIT = "unit"
    PROJECT = "project"
    FIRMWARE = "firmware"
    CATEGORY = "category"
    LOCATION = "location"


@dataclass(frozen=True, slots=True)
class SearchText:
    """What the workspace is searched for: trimmed, one to 100 characters (requirement 1.5)."""

    value: str

    @classmethod
    def of(cls, raw: str) -> SearchText:
        text = raw.strip()
        if not text:
            raise InvalidSearchError("type something to search for")
        if len(text) > MAX_TEXT_LENGTH:
            raise InvalidSearchError(f"a search takes at most {MAX_TEXT_LENGTH} characters")
        return cls(text)


@dataclass(frozen=True, slots=True)
class SearchHit:
    """One record found: its kind and id, a title, and a detail when it has one (1.2)."""

    kind: SearchKind
    id: UUID
    title: str
    detail: str | None


@dataclass(frozen=True, slots=True)
class SearchGroup:
    """One kind's hits, in its module's order, and whether more match than it holds."""

    kind: SearchKind
    hits: tuple[SearchHit, ...]
    more: bool


@dataclass(frozen=True, slots=True)
class SearchResults:
    """What the workspace answered for a text: a group per kind that found something, in
    `SearchKind`'s order (requirement 1.3)."""

    text: str
    groups: tuple[SearchGroup, ...]


def group(kind: SearchKind, found: Sequence[SearchHit], limit: int) -> SearchGroup | None:
    """The first `limit` of what a kind found, which it was asked `limit + 1` of, and whether the
    extra one came back; no group for a kind that found nothing (property 1)."""
    if not found:
        return None
    return SearchGroup(kind, tuple(found[:limit]), more=len(found) > limit)


def results(text: SearchText, groups: Iterable[SearchGroup | None]) -> SearchResults:
    """The groups that found something, in `SearchKind`'s order whatever order they came in."""
    kept = [found for found in groups if found is not None]
    order = list(SearchKind)
    kept.sort(key=lambda found: order.index(found.kind))
    return SearchResults(text.value, tuple(kept))
