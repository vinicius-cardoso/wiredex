"""The trash as one list: four kinds of record, newest first, read a numbered page at a time.

Each module keeps its own records in the trash and answers its newest ones with how many it holds
(decision 9); this file is what makes one page of the four. The order is `(trashed_at, id)`
descending, and ids are UUIDv7, unique across tables, so the order is total whatever the kinds,
and every page holds the records the one before it stopped at.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from wiredex.shared_kernel.domain.paging import Page, PageRequest
from wiredex.shared_kernel.domain.trash import TrashedSlice, TrashPosition
from wiredex.trash.domain.errors import InvalidTrashFilterError

# A fragment of a name or detail to narrow the list by: as long as the box it is typed in.
MAX_FILTER_TEXT_LENGTH = 80


class TrashKind(StrEnum):
    """Which record a trashed item is, and which module's bin holds it (decision 8)."""

    PART = "part"
    UNIT = "unit"
    PROJECT = "project"
    FIRMWARE = "firmware"


@dataclass(frozen=True, slots=True)
class TrashedItem:
    """One record in the trash, as the trash page lists it (requirement 4.1)."""

    kind: TrashKind
    id: UUID
    name: str  # a unit's is its code
    detail: str | None  # a part's MPN, a unit's part, a firmware's target
    trashed_at: datetime

    @property
    def position(self) -> TrashPosition:
        return TrashPosition(self.trashed_at, self.id)


@dataclass(frozen=True, slots=True)
class TrashFilter:
    """What narrows the trash: one kind, a fragment of a record's name or detail, or both.

    The text is trimmed and its whitespace collapsed, and it matches ignoring case; a blank one
    narrows nothing. Neither set is the whole trash. Each module matches the text in its own
    SQL with `ILIKE`; `matches` says the same in Python, comparing with `lower()` as `ILIKE`
    does, not `casefold()`.
    """

    kind: TrashKind | None = None
    text: str | None = None

    def __post_init__(self) -> None:
        if self.text is None:
            return
        collapsed = " ".join(self.text.split())
        if len(collapsed) > MAX_FILTER_TEXT_LENGTH:
            raise InvalidTrashFilterError(
                f"the text to search the trash by is at most {MAX_FILTER_TEXT_LENGTH} characters"
            )
        object.__setattr__(self, "text", collapsed or None)

    def keeps(self, kind: TrashKind) -> bool:
        """Whether records of the kind can match: the bin of any other kind isn't asked."""
        return self.kind is None or self.kind is kind

    def matches(self, item: TrashedItem) -> bool:
        if not self.keeps(item.kind):
            return False
        if self.text is None:
            return True
        needle = self.text.lower()
        return any(needle in field.lower() for field in (item.name, item.detail) if field)


def page_of(shares: Iterable[TrashedSlice[TrashedItem]], request: PageRequest) -> Page[TrashedItem]:
    """One page of the trash out of each kind's newest `request.reach` matches and its total.

    The newest `reach` records of all kinds are each among their own kind's newest `reach`, so
    every record up to the end of the page is here. A request past the end is served as the last
    page: then `reach` is beyond every kind's total, so each kind gave all it holds.
    """
    held = list(shares)
    total = sum(share.total for share in held)
    served = request.within(total)
    found = sorted(
        (item for share in held for item in share.items),
        key=lambda item: item.position,
        reverse=True,
    )
    return Page(tuple(found[served.offset : served.offset + served.size]), total, served)
