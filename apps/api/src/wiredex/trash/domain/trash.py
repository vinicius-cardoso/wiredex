"""The trash as one list: four kinds of record, newest first, read a page at a time.

Each module keeps its own records in the trash and pages them from a position (decision 9); this
file is what makes one list of the four pages. The order is `(trashed_at, id)` descending, and ids
are UUIDv7, unique across tables, so the order is total whatever the kinds: a cursor is a
position, and a page is every record before it, the newest `limit` first.
"""

import base64
import binascii
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from wiredex.shared_kernel.domain.trash import TrashPosition
from wiredex.trash.domain.errors import InvalidTrashCursorError, InvalidTrashFilterError

# A cursor is a time and a UUID: short. Anything much longer was never one.
MAX_CURSOR_LENGTH = 200

# How many records one read answers: 50 unless asked, never more than 100 (requirement 4.2).
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100

# A fragment of a name or detail to narrow the list by: as long as the box it is typed in.
MAX_FILTER_TEXT_LENGTH = 80

_SEPARATOR = "|"


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
    narrows nothing. Neither set is the whole trash.
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
        needle = self.text.casefold()
        return any(needle in field.casefold() for field in (item.name, item.detail) if field)


@dataclass(frozen=True, slots=True)
class TrashCursor:
    """Where the last page stopped: the last record's position, as opaque base64url text."""

    position: TrashPosition

    def encode(self) -> str:
        raw = f"{self.position.trashed_at.isoformat()}{_SEPARATOR}{self.position.id}"
        return base64.urlsafe_b64encode(raw.encode()).decode()

    @classmethod
    def decode(cls, text: str) -> TrashCursor:
        """The cursor the text carries. Every way of being malformed is the same refusal, since a
        client never builds a cursor, it only echoes the one it was given (requirement 4.4)."""
        if len(text) > MAX_CURSOR_LENGTH:
            raise InvalidTrashCursorError("this cursor can't be read")
        try:
            raw = base64.urlsafe_b64decode(text.encode()).decode()
            moment, identity = raw.split(_SEPARATOR)
            trashed_at = datetime.fromisoformat(moment)
            item_id = UUID(identity)
        except (ValueError, binascii.Error) as error:
            raise InvalidTrashCursorError("this cursor can't be read") from error
        if trashed_at.tzinfo is None:
            raise InvalidTrashCursorError("this cursor can't be read")
        return cls(TrashPosition(trashed_at, item_id))


@dataclass(frozen=True, slots=True)
class TrashPage:
    """A page of the trash, and the cursor reading the next one, or None for the last page."""

    items: tuple[TrashedItem, ...]
    next: TrashCursor | None


def merge(pages: Iterable[Sequence[TrashedItem]], limit: int) -> TrashPage:
    """The newest `limit` records of every kind's page, and a cursor when any is left over.

    Each page holds its kind's newest records before the same position, up to `limit + 1` of
    them. The newest `limit` of all kinds are each among their own kind's newest `limit`, so
    they are all here; and more than `limit` records here means at least one is left for the
    next page, while `limit` or fewer means every kind gave everything it had.
    """
    found = sorted(
        (item for page in pages for item in page), key=lambda item: item.position, reverse=True
    )
    kept = tuple(found[:limit])
    if len(found) <= limit or not kept:
        return TrashPage(kept, None)
    return TrashPage(kept, TrashCursor(kept[-1].position))
