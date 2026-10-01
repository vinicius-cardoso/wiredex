"""A firmware's versions: each one a snapshot of its source, numbered by SemVer, a draft until
it is released and never changed after (ADR 0006, decision 7).

A version's files live in their own table and reach it as `SourceFiles`, so the entity holds
its number, changelog and status. The use cases ask `ensure_editable` before they write a file,
under the firmware's lock (decision 8).
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from wiredex.firmware.domain.errors import (
    InvalidVersionError,
    NoChangelogError,
    NoFilesError,
    VersionNotFoundError,
    VersionReleasedError,
    VersionTakenError,
)
from wiredex.firmware.domain.firmware import Firmware
from wiredex.firmware.domain.semver import MAX_VERSION_LENGTH, SemVer, suggested_version
from wiredex.firmware.domain.source import SourceFiles
from wiredex.firmware.domain.values import Changelog, FirmwareId, VersionId, WorkspaceId


class VersionStatus(StrEnum):
    """A draft is still being written: its number, changelog and files can change. A released
    version's never change again, and a change means a new version (decision 7)."""

    DRAFT = "draft"
    RELEASED = "released"


@dataclass(eq=False)
class FirmwareVersion:
    """One snapshot of a firmware's source: its number, its changelog, its status, and the
    version it was started from.

    Its firmware and workspace always come from the firmware it is drafted in, never from an
    argument that could disagree with them.
    """

    id: VersionId
    workspace_id: WorkspaceId
    firmware_id: FirmwareId
    number: SemVer  # the `version` column; `version.number` never reads `version.version`
    changelog: Changelog | None
    status: VersionStatus
    based_on: VersionId | None
    created_at: datetime
    updated_at: datetime
    released_at: datetime | None = None

    @classmethod
    def draft(
        cls,
        version_id: VersionId,
        firmware: Firmware,
        number: SemVer,
        base: FirmwareVersion | None,
        now: datetime,
    ) -> FirmwareVersion:
        """A new draft of the firmware with no changelog, empty or started from `base`, which
        it records (requirement 5.5).

        The base is any version of the same firmware, draft or released; one of another
        firmware is a 404 (5.9). Copying its files under new ids is the use case's, and so is
        asking the firmware's versions whether the number is free, before this.
        """
        if base is not None and base.firmware_id != firmware.id:
            raise VersionNotFoundError("that version isn't one of this firmware's")
        return cls(
            id=version_id,
            workspace_id=firmware.workspace_id,
            firmware_id=firmware.id,
            number=number,
            changelog=None,
            status=VersionStatus.DRAFT,
            based_on=None if base is None else base.id,
            created_at=now,
            updated_at=now,
        )

    def ensure_editable(self) -> None:
        """Refuses a released version with 409 `version_released` (requirements 6.4, 6.5): a
        number written in a board's log always means the same code. Every write to a version's
        number, changelog or files asks it first."""
        if self.status is VersionStatus.RELEASED:
            raise VersionReleasedError(
                f"{self.number} is released, and a released version never changes: start a "
                "new version from it"
            )

    def revise(self, number: SemVer, changelog: Changelog | None, now: datetime) -> bool:
        """Replaces a draft's number and changelog whole (requirement 5.7). A released
        version's are refused, even unchanged (6.4).

        Whether the number is free is the firmware's versions' to say, before this. Returns
        whether anything changed, so an edit that changes nothing commits nothing.
        """
        self.ensure_editable()
        if (self.number, self.changelog) == (number, changelog):
            return False
        self.number = number
        self.changelog = changelog
        self.updated_at = now
        return True

    def release(self, files: SourceFiles, now: datetime) -> None:
        """Marks the draft released and records when (requirement 6.1), for good.

        `files` are the draft's own, read under its firmware's lock. Refused, changing
        nothing: a version already released (6.5); then a draft holding no file (6.2), which
        is no code to flash; then one with no changelog (6.3), which would be a number with no
        story (decision 7).
        """
        self.ensure_editable()
        if not files.items:
            raise NoFilesError(f"{self.number} has no source file to release")
        if self.changelog is None:
            raise NoChangelogError(
                f"{self.number} has no changelog: say what it changed before releasing it"
            )
        self.status = VersionStatus.RELEASED
        self.released_at = now
        self.updated_at = now

    def touch(self, now: datetime) -> None:
        """One of its files changed: the version's last change moves with it."""
        self.updated_at = now


def _number(version: FirmwareVersion) -> SemVer:
    return version.number


@dataclass(frozen=True, slots=True)
class FirmwareVersions:
    """One firmware's versions, highest first (requirement 5.3), and the rules that look across
    them: which is highest, which release is latest, and which number a version takes.

    Built from the one read a repository makes, under the firmware's lock when a version is
    about to be numbered (decision 8), so a number it answers free stays free until the
    transaction ends.
    """

    items: tuple[FirmwareVersion, ...] = ()

    def __post_init__(self) -> None:
        # Sorted here rather than trusted from the caller, as 08's revisions are, so `highest`
        # and the order the page shows can't depend on how a repository read the rows. A
        # firmware's numbers are distinct, so the order is total.
        object.__setattr__(self, "items", tuple(sorted(self.items, key=_number, reverse=True)))

    @classmethod
    def of(cls, versions: Iterable[FirmwareVersion]) -> FirmwareVersions:
        return cls(tuple(versions))

    @property
    def highest(self) -> FirmwareVersion | None:
        """The version of highest precedence, draft or released: the one a firmware's page
        opens (requirement 11.5). None for a firmware with no version."""
        return self.items[0] if self.items else None

    @property
    def latest_release(self) -> FirmwareVersion | None:
        """The released version of highest precedence, whenever it was released; a draft
        above it doesn't hide it. None before the first release."""
        released = (version for version in self.items if version.status is VersionStatus.RELEASED)
        return next(released, None)

    def newer_than(self, number: SemVer) -> FirmwareVersion | None:
        """The latest release when it is above `number`, the version a board runs, else None
        (15's decision 10). A released pre-release counts, since the owner released it; a draft
        never does, since it isn't code to flash yet."""
        latest = self.latest_release
        return latest if latest is not None and number < latest.number else None

    def suggested(self) -> SemVer:
        """0.1.0 for a firmware with no version, else the successor of the highest
        (requirement 5.4), which no version holds. A firmware's page shows it (1.8) even when
        it is too long to be a version's number, which `number_for` then refuses."""
        return suggested_version([version.number for version in self.items])

    def number_for(self, asked: SemVer | None, renaming: FirmwareVersion | None = None) -> SemVer:
        """The number asked for, refused when a version other than `renaming` holds it
        (requirements 5.2, 5.7); or the suggested one when none is asked (5.4).

        A typed number is at most 64 characters, `SemVer.parse`'s cap, but the successor of one
        within two characters of it can be longer, which the column can't store: that
        suggestion is refused, asking for a number to be typed instead.
        """
        if asked is None:
            return self._suggestion()
        for version in self.items:
            if version is not renaming and version.number == asked:
                raise VersionTakenError(
                    f"this firmware already has a version {asked}", item=str(asked)
                )
        return asked

    def get(self, version_id: VersionId) -> FirmwareVersion | None:
        return next((version for version in self.items if version.id == version_id), None)

    def _suggestion(self) -> SemVer:
        suggested = self.suggested()
        length = len(str(suggested))
        if length > MAX_VERSION_LENGTH:
            raise InvalidVersionError(
                f"the next number, {suggested}, would have {length} characters, and a version "
                f"number has at most {MAX_VERSION_LENGTH}: type a number for this version"
            )
        return suggested
