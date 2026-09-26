import re
from dataclasses import dataclass
from enum import StrEnum
from typing import NewType
from uuid import UUID

from wiredex.inventory.domain.errors import (
    InvalidLocationNameError,
    InvalidNoteError,
    InvalidQuantityError,
    InvalidShortCodeError,
)

# Inventory declares its own WorkspaceId and PartId instead of importing catalog's: modules
# don't import each other's domain. Promote WorkspaceId to the shared kernel when a third
# module needs it. PartId is catalog's PartDefinitionId, named locally.
WorkspaceId = NewType("WorkspaceId", UUID)
LocationId = NewType("LocationId", UUID)
StockLotId = NewType("StockLotId", UUID)
StockMovementId = NewType("StockMovementId", UUID)
MoveGroupId = NewType("MoveGroupId", UUID)
PartId = NewType("PartId", UUID)


MAX_LOCATION_NAME_LENGTH = 80


@dataclass(frozen=True, slots=True)
class LocationName:
    """A location's name, kept as cased: *Drawer 3* is the owner's spelling, not noise."""

    value: str

    def __post_init__(self) -> None:
        # Trim and collapse inner runs of whitespace, then refuse empty or over-long.
        collapsed = " ".join(self.value.split())
        if not 1 <= len(collapsed) <= MAX_LOCATION_NAME_LENGTH:
            raise InvalidLocationNameError(
                f"a location name needs between 1 and {MAX_LOCATION_NAME_LENGTH} characters"
            )
        object.__setattr__(self, "value", collapsed)

    def __str__(self) -> str:
        return self.value


# The short code scheme: WX-, then L for a location or U for a unit, then at least four
# digits. Four is the display minimum; a workspace past 9999 widens to five without wrapping,
# because the width is display, not identity.
_SHORT_CODE = re.compile(r"^WX-[LU]-\d{4,}$")


@dataclass(frozen=True, slots=True)
class ShortCode:
    """A human-readable label like WX-L-0007, sequential per workspace. No QR (decision 3)."""

    value: str

    def __post_init__(self) -> None:
        code = self.value.strip().upper()
        if not _SHORT_CODE.match(code):
            raise InvalidShortCodeError(f"{self.value!r} is not a short code like WX-L-0007")
        object.__setattr__(self, "value", code)

    @classmethod
    def for_location(cls, number: int) -> ShortCode:
        """The location code for a counter value: WX-L-0001, widening past 9999 to WX-L-10000."""
        return cls(f"WX-L-{number:04d}")

    @classmethod
    def for_unit(cls, number: int) -> ShortCode:
        """The unit code for a counter value: WX-U-0001. Units are minted by the next spec."""
        return cls(f"WX-U-{number:04d}")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class Quantity:
    """A non-negative count, the amount *in* a lot. A movement's signed change is a plain int."""

    value: int

    def __post_init__(self) -> None:
        # bool is an int subclass; a quantity is a count, not a flag.
        if isinstance(self.value, bool) or not isinstance(self.value, int):
            raise InvalidQuantityError("a quantity needs to be a whole number")
        if self.value < 0:
            raise InvalidQuantityError("a quantity can't be negative")

    def __int__(self) -> int:
        return self.value

    def __str__(self) -> str:
        return str(self.value)


class MovementKind(StrEnum):
    """ADR 0002's seven kinds. v0.4.0 writes only the first three; the rest arrive in v0.5.0.

    The domain accepts all seven and the ledger's CHECK lists all seven, so v0.5.0 adds
    behaviour, not a migration. A StrEnum, so the kind reaches JSON and the CHECK as its name.
    """

    RECEIVE = "RECEIVE"
    ADJUST = "ADJUST"
    MOVE = "MOVE"
    RESERVE = "RESERVE"
    RELEASE = "RELEASE"
    CONSUME = "CONSUME"
    RETURN = "RETURN"


class MovementReason(StrEnum):
    """Why an ADJUST happened. RECEIVE and MOVE carry no reason."""

    RECOUNT = "recount"
    DAMAGED = "damaged"
    LOST = "lost"
    FOUND = "found"
    CORRECTION = "correction"


MAX_NOTE_LENGTH = 500


@dataclass(frozen=True, slots=True)
class Note:
    """An optional free-text note on a movement, trimmed and capped."""

    value: str

    def __post_init__(self) -> None:
        collapsed = " ".join(self.value.split())
        if not 1 <= len(collapsed) <= MAX_NOTE_LENGTH:
            raise InvalidNoteError(f"a note needs between 1 and {MAX_NOTE_LENGTH} characters")
        object.__setattr__(self, "value", collapsed)

    def __str__(self) -> str:
        return self.value
