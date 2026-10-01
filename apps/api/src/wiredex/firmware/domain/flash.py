"""The flash log: which released version went onto which unit, when, and why (ADR 0006's
deployment log, 15-flash-log). A unit's current version is its newest flash.

A unit is inventory's, so firmware sees it as `UnitFacts`, plain values the composition root
reads from inventory (decision 8), and a flash keeps the unit's code and revision as they were
when it was logged (decision 3).
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from wiredex.firmware.domain.errors import (
    FirmwareError,
    FlashedInFutureError,
    InvalidNotesError,
    NotReleasedError,
    UnitRetiredError,
)
from wiredex.firmware.domain.semver import SemVer
from wiredex.firmware.domain.values import (
    FlashId,
    RevisionId,
    UnitId,
    VersionId,
    WorkspaceId,
    _one_line,
)
from wiredex.firmware.domain.version import FirmwareVersion, VersionStatus

MAX_UNIT_CODE_LENGTH = 16
MAX_NOTES_LENGTH = 500
FUTURE_ALLOWANCE = timedelta(minutes=5)  # a phone's clock a little ahead of the server's


@dataclass(frozen=True, slots=True)
class UnitCode:
    """A unit's short code as inventory minted it, `WX-U-0042`: 1 to 16 characters, kept as
    given. Inventory mints a code once and never changes or reuses it, so a flash that keeps it
    still names its board after the unit is deleted (requirement 1.8)."""

    value: str

    def __post_init__(self) -> None:
        # Inventory's codes always fit, so this guards the column, not what anyone types.
        if not 1 <= len(self.value) <= MAX_UNIT_CODE_LENGTH:
            raise FirmwareError(
                f"a unit code needs between 1 and {MAX_UNIT_CODE_LENGTH} characters"
            )

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class FlashNotes:
    """Why or how a board was flashed, *bench test before the build*: trimmed and collapsed, 1
    to 500 characters, no control character or half of a surrogate pair (requirement 1.9). One
    line, as a BOM line's notes are, since the log shows them in a table cell. Blank notes are
    none, which the edge reads as None before they get here."""

    value: str

    def __post_init__(self) -> None:
        notes = _one_line(self.value, MAX_NOTES_LENGTH, "a flash's note", InvalidNotesError)
        object.__setattr__(self, "value", notes)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class UnitFacts:
    """A unit as firmware sees it (decision 8): plain values, no inventory type."""

    unit_id: UnitId
    code: UnitCode
    retired: bool
    revision_id: RevisionId | None  # the revision holding it, while reserved or in use


@dataclass(frozen=True, slots=True)
class FlashDetails:
    """What the owner says of a flash beside its unit and version: when it was done, or None
    for now, and its notes."""

    flashed_at: datetime | None = None
    notes: FlashNotes | None = None


@dataclass(frozen=True, slots=True)
class Flash:
    """One entry of a unit's flash log. Never edited: a wrong entry is removed and logged again
    (decision 5).

    Its workspace comes from the version, and the unit's code and revision are copies taken
    when it was logged, so the entry keeps naming its board and its build after the unit is
    deleted or the build is cancelled or dismantled (requirements 1.7, 1.8).
    """

    id: FlashId
    workspace_id: WorkspaceId
    unit_id: UnitId
    unit_code: UnitCode
    version_id: VersionId
    revision_id: RevisionId | None  # the unit's, when the flash was logged (decision 3)
    flashed_at: datetime
    notes: FlashNotes | None
    created_at: datetime

    @classmethod
    def record(
        cls,
        flash_id: FlashId,
        unit: UnitFacts,
        version: FirmwareVersion,
        details: FlashDetails,
        now: datetime,
    ) -> Flash:
        """The released version flashed onto the unit, at the time given or now when none is
        (requirements 1.1, 1.2), with the unit's code and the revision holding it now.

        Refused, in this order: a draft (1.5, decision 2), a retired unit (1.6, decision 7),
        then a time more than five minutes past `now` (1.4). A time before the version was
        released is taken (1.3): the board may have run that code before it was released here.
        """
        if version.status is not VersionStatus.RELEASED:
            raise NotReleasedError(
                f"{version.number} is a draft and can still change: release it before logging "
                "a flash of it",
                item=str(version.number),
            )
        if unit.retired:
            raise UnitRetiredError(
                f"{unit.code} is retired: un-retire it before logging a flash on it",
                item=str(unit.code),
            )
        flashed_at = now if details.flashed_at is None else details.flashed_at
        if flashed_at > now + FUTURE_ALLOWANCE:
            raise FlashedInFutureError("a flash can't be dated more than five minutes from now")
        return cls(
            id=flash_id,
            workspace_id=version.workspace_id,
            unit_id=unit.unit_id,
            unit_code=unit.code,
            version_id=version.id,
            revision_id=unit.revision_id,
            flashed_at=flashed_at,
            notes=details.notes,
            created_at=now,
        )

    def order(self) -> tuple[datetime, datetime, UUID]:
        """When it was flashed, then when it was logged, then its id, a UUIDv7 and so ordered
        by time too: a total order, so two flashes with one time still order (decision 4)."""
        return (self.flashed_at, self.created_at, self.id)


@dataclass(frozen=True, slots=True)
class FlashLog:
    """A unit's flashes, newest first (decision 4), and the one it runs: the first.

    A flash backdated to last week takes its place in the history without becoming current.
    """

    items: tuple[Flash, ...] = ()

    def __post_init__(self) -> None:
        # Sorted here rather than trusted from the caller, as a firmware's versions are, so the
        # current version can't depend on how a repository read the rows.
        newest_first = tuple(sorted(self.items, key=Flash.order, reverse=True))
        object.__setattr__(self, "items", newest_first)

    @classmethod
    def of(cls, flashes: Iterable[Flash]) -> FlashLog:
        return cls(tuple(flashes))

    @property
    def current(self) -> Flash | None:
        """The newest flash, whose version the board runs (requirement 2.2), or None for a
        unit never flashed."""
        return self.items[0] if self.items else None


@dataclass(frozen=True, slots=True)
class BlockingFlash:
    """A flash that keeps a version from being deleted, its version's number, and whether
    inventory still holds its unit (decision 6): the page links the unit only then, and offers
    to remove the flash either way."""

    flash: Flash
    number: SemVer
    unit_present: bool
