"""What the firmware use cases need from the outside, as Protocols over domain types.

No repository method takes a workspace: the unit of work is built for one workspace and its
repositories only ever see that workspace's rows (ADR 0007). The unit of work exposes them as
read-only properties, because a protocol attribute would have to match exactly, so
`SqlFirmwares` wouldn't count as `Firmwares`.

Firmware imports no other module (ADR 0001). What it reads of projects' revisions arrives
through `RevisionDirectory`, as `RevisionFacts` of plain values, bound by bootstrap to the
session firmware's unit of work opened (decision 5); what a fork copies of it goes through
`FirmwareRepositories`, bound to the fork's session (decision 4). The views live here too, next
to the ports they travel through, as projects' do.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from wiredex.firmware.domain.firmware import Firmware
from wiredex.firmware.domain.semver import SemVer
from wiredex.firmware.domain.source import SourceFile, SourceFiles
from wiredex.firmware.domain.values import FirmwareId, FirmwareName, RevisionId, VersionId
from wiredex.firmware.domain.version import FirmwareVersion, FirmwareVersions
from wiredex.shared_kernel.application.ports import UnitOfWork

# --- Projects' revisions, in firmware's words (decision 5) ----------------------------------


@dataclass(frozen=True, slots=True)
class RevisionFacts:
    """A revision as firmware names it: its project, its label and its summary (requirement
    3.5). Plain values, no projects type: bootstrap reads projects' own ref into these."""

    revision_id: RevisionId
    project_id: UUID
    project_name: str
    label: str
    summary: str | None


class RevisionDirectory(Protocol):
    """Projects' revisions, read on the session firmware's unit of work opened (decision 5): one
    workspace setting scopes both modules' rows, and a read is one transaction."""

    async def refs(
        self, revision_ids: Collection[RevisionId]
    ) -> Mapping[RevisionId, RevisionFacts]:
        """The listed revisions the workspace holds, in one read. Any other is absent, another
        workspace's and a deleted one's alike (decision 3)."""
        ...


# --- Firmware's own rows ---------------------------------------------------------------------


class Firmwares(Protocol):
    async def add(self, firmware: Firmware) -> None:
        """Flushed at once, so a link written with Core in the same transaction finds it."""
        ...

    async def get(self, firmware_id: FirmwareId) -> Firmware | None: ...

    async def locked(self, firmware_id: FirmwareId) -> Firmware | None:
        """The firmware, its row locked until the transaction ends and read fresh (decision 8).

        Every write to a firmware, its links, its versions or their files takes it first, so
        writes to one firmware take turns: its version numbers stay distinct, and no file lands
        in a version after its release commits (requirement 6.7).
        """
        ...

    async def named(self, name: FirmwareName) -> Firmware | None:
        """The firmware holding the name, compared folded as the unique index folds it."""
        ...

    async def matching(self, text: str) -> list[Firmware]:
        """The firmware whose name or target holds the text, ignoring case, with `%` and `_`
        matching only themselves; every firmware for empty text (requirement 2.3).

        Last change first (2.2). Two changed at one instant come newer id first, the ids being
        time-ordered, so the order is stable.
        """
        ...

    async def running_on(self, revision_id: RevisionId) -> list[Firmware]:
        """The firmware linked to the revision, in one join, by name folded (requirement 3.4)."""
        ...

    async def remove(self, firmware: Firmware) -> None:
        """The firmware and, by the database's cascade and the fakes' own, its versions, their
        files and its links (requirement 1.9)."""
        ...


@dataclass(frozen=True, slots=True)
class VersionSummary:
    """A version as its firmware's page lists it, with how many files it holds and their bytes,
    summed from the stored sizes without reading the text (decision 9)."""

    version: FirmwareVersion
    files: int
    size: int


class Versions(Protocol):
    async def add(self, version: FirmwareVersion) -> None:
        """Flushed at once, so its files, written with Core, can follow in the same
        transaction."""
        ...

    async def get(self, version_id: VersionId) -> FirmwareVersion | None: ...

    async def firmware_of(self, version_id: VersionId) -> FirmwareId | None:
        """The version's firmware id alone, no entity (decision 8): what `lock_version` locks
        before it reads the version itself."""
        ...

    async def of_firmware(self, firmware_id: FirmwareId) -> FirmwareVersions: ...

    async def summaries(
        self, firmware_ids: Collection[FirmwareId]
    ) -> Mapping[FirmwareId, tuple[VersionSummary, ...]]:
        """Each listed firmware's versions, highest first, with their file counts and sizes, in
        one aggregate whatever their numbers (decision 12). A firmware with no version may be
        absent."""
        ...

    async def remove(self, version: FirmwareVersion) -> None:
        """The version and, by the cascade, its files. A version based on it keeps going, its
        `based_on` cleared (requirement 8.2)."""
        ...


class Sources(Protocol):
    """A version's files, written with Core as 09's BOM lines are: a file has no identity worth
    an ORM object, and a batch is one insert."""

    async def of_version(self, version_id: VersionId) -> SourceFiles: ...

    async def add_all(self, version_id: VersionId, files: Sequence[SourceFile]) -> None:
        """Many files at once, a batch or a base's copy: one statement whatever their number."""
        ...

    async def update(self, version_id: VersionId, before: SourceFile, after: SourceFile) -> None:
        """The file's new path and text, under the id it keeps (decision 10)."""
        ...

    async def remove(self, version_id: VersionId, file: SourceFile) -> None: ...


class RevisionLinks(Protocol):
    """The revisions each firmware runs on (decision 2). Firmware's own rows, each naming its
    revision by a bare id, so a link outlives its revision (decision 3)."""

    async def of_firmware(self, firmware_id: FirmwareId) -> tuple[RevisionId, ...]:
        """The revisions the firmware is linked to, in the order they were linked (requirement
        3.5); two linked at one instant by the revision's id."""
        ...

    async def add(self, firmware_id: FirmwareId, revision_id: RevisionId, at: datetime) -> bool:
        """Links them, dated `at`, and answers whether the link is new. One already there is
        kept as it was, its date included, so a repeated link writes nothing (requirement
        3.1)."""
        ...

    async def remove(self, firmware_id: FirmwareId, revision_id: RevisionId) -> bool:
        """Unlinks them, and answers whether there was a link to remove (requirement 3.2)."""
        ...

    async def copy(self, source: RevisionId, target: RevisionId, at: datetime) -> None:
        """The source's links given to the target, dated `at`, and each of those firmware's last
        change moved to `at`: two statements in SQL, both done by the fake too (decision 4)."""
        ...


class FirmwareUnitOfWork(UnitOfWork, Protocol):
    async def clear(self) -> None:
        """Every firmware of the workspace, with its versions, files and links, for a demo bench
        being restored."""
        ...

    @property
    def firmwares(self) -> Firmwares: ...

    @property
    def versions(self) -> Versions: ...

    @property
    def sources(self) -> Sources: ...

    @property
    def links(self) -> RevisionLinks: ...


class RunsOnUnitOfWork(FirmwareUnitOfWork, Protocol):
    """Firmware's unit of work that also reads projects' revisions on its session (decision 5).

    A port of its own, as projects' `BuildUnitOfWork` extends `BomUnitOfWork`: bootstrap binds
    `revisions`, and since it is a `FirmwareUnitOfWork` too, one factory of it serves every
    firmware use case.
    """

    @property
    def revisions(self) -> RevisionDirectory: ...


class FirmwareRepositories(Protocol):
    """The links with no commit, for a fork's transaction (decision 4).

    Code that takes only this can write inside a transaction projects opened, and can never end
    it: `CopyRevisionLinks` runs over it inside a fork, as catalog's `PartDrafts` runs over
    `CatalogRepositories` inside an intake.
    """

    @property
    def links(self) -> RevisionLinks: ...


# --- Views: the shapes the use cases hand back ----------------------------------------------


@dataclass(frozen=True, slots=True)
class FirmwareView:
    """A firmware's page (requirement 1.8): its details, its versions with their counts and
    sizes, the revisions it runs on, its latest release and the number a new version takes."""

    firmware: Firmware
    versions: tuple[VersionSummary, ...]  # highest first
    runs_on: tuple[RevisionFacts, ...]  # link order, revisions the workspace lost left out
    latest_release: FirmwareVersion | None
    suggested: SemVer


@dataclass(frozen=True, slots=True)
class FirmwareSummary:
    """A row of the firmware list, or of a revision's firmware (requirements 2.1, 3.4)."""

    firmware: Firmware
    latest_release: FirmwareVersion | None
    versions: int
    drafts: int


@dataclass(frozen=True, slots=True)
class VersionView:
    """A version as it opens (requirement 5.8): the version, the one it was started from while
    that one exists, and its files in requirement 7.10's order."""

    version: FirmwareVersion
    base: FirmwareVersion | None
    files: SourceFiles
