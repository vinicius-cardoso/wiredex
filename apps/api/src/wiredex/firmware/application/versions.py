"""A firmware's versions: start one, edit a draft, release it, delete one, and open one.

Every write locks the firmware's row first (decision 8): starting a version through
`lock_firmware`, the others through `lock_version`, which reads the version only once its
firmware is locked. So version numbers stay distinct, a release reads the files the write
before it left, and no file lands in a version after its release commits (requirement 6.7).
A write moves its firmware's last change (requirement 2.2), and one that changes nothing
commits nothing. A write that answers a version reads it before its commit, since the
workspace setting row-level security reads ends with the transaction (ADR 0007).
"""

from wiredex.firmware.application.firmware import (
    FlashUnitOfWorkFactory,
    UnitOfWorkFactory,
    blocking_flashes,
    flashed_message,
    lock_firmware,
)
from wiredex.firmware.application.ports import FirmwareUnitOfWork, VersionView
from wiredex.firmware.domain.errors import VersionFlashedError, VersionNotFoundError
from wiredex.firmware.domain.firmware import Firmware
from wiredex.firmware.domain.semver import SemVer
from wiredex.firmware.domain.source import SourceFile, SourceFiles
from wiredex.firmware.domain.values import (
    Changelog,
    FirmwareId,
    SourceFileId,
    VersionId,
    WorkspaceId,
)
from wiredex.firmware.domain.version import FirmwareVersion, FirmwareVersions, VersionStatus
from wiredex.shared_kernel.application.ports import Clock, IdGenerator


class StartVersion:
    """A new draft of a firmware (requirement 5.5), numbered as asked or as suggested (5.4):
    empty, or holding a copy of every file of the version of the same firmware it starts from,
    which it records and leaves as it was, released or not (6.6)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory, clock: Clock, ids: IdGenerator) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._ids = ids

    async def __call__(
        self,
        workspace_id: WorkspaceId,
        firmware_id: FirmwareId,
        number: SemVer | None = None,
        base_id: VersionId | None = None,
    ) -> VersionView:
        async with self._unit_of_work(workspace_id) as work:
            firmware = await lock_firmware(work, firmware_id)
            versions = await work.versions.of_firmware(firmware.id)
            # The base before the number: a draft started from a version that went is a 404,
            # whatever it is numbered.
            base = None if base_id is None else _base_among(versions, base_id)
            numbered = versions.number_for(number)
            files = SourceFiles() if base is None else await self._copies(work, base)
            now = self._clock.now()
            version = FirmwareVersion.draft(
                VersionId(self._ids.new_id()), firmware, numbered, base, now
            )
            await work.versions.add(version)
            if files.items:
                await work.sources.add_all(version.id, files.items)
            firmware.touch(now)
            await work.commit()
            return VersionView(version, base, files)

    async def _copies(self, work: FirmwareUnitOfWork, base: FirmwareVersion) -> SourceFiles:
        """The base's files under new ids, minted in the base's order. A copy meets the limits
        a write does (decision 9), which the base's files already met."""
        held = await work.sources.of_version(base.id)
        return SourceFiles.of(
            SourceFile(SourceFileId(self._ids.new_id()), file.path, file.text)
            for file in held.items
        )


class UpdateVersion:
    """Replaces a draft's number and changelog whole (requirement 5.7), its own number not
    counting against it; the ones it already has write nothing. A released version's are
    refused, even unchanged (6.4)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory, clock: Clock) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    async def __call__(
        self,
        workspace_id: WorkspaceId,
        version_id: VersionId,
        number: SemVer,
        changelog: Changelog | None,
    ) -> VersionView:
        async with self._unit_of_work(workspace_id) as work:
            firmware, version = await lock_version(work, version_id)
            version.ensure_editable()
            # Only a new number can be another version's. The version is told apart from the
            # others as the read it is checked against holds it.
            if number != version.number:
                versions = await work.versions.of_firmware(firmware.id)
                versions.number_for(number, renaming=versions.get(version.id))
            now = self._clock.now()
            changed = version.revise(number, changelog, now)
            view = await _view(work, version)
            if changed:
                firmware.touch(now)
                await work.commit()
            return view


class ReleaseVersion:
    """Marks a draft released and records when (requirement 6.1), once it holds a file (6.2)
    and a changelog (6.3). A released version isn't released again (6.5)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory, clock: Clock) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    async def __call__(self, workspace_id: WorkspaceId, version_id: VersionId) -> VersionView:
        async with self._unit_of_work(workspace_id) as work:
            firmware, version = await lock_version(work, version_id)
            # Read under the lock, so these are the files it is released with: no write to
            # them can come between this read and the commit.
            files = await work.sources.of_version(version.id)
            now = self._clock.now()
            version.release(files, now)
            firmware.touch(now)
            view = VersionView(version, await _base_of(work, version), files)
            await work.commit()
            return view


class DeleteVersion:
    """A version with its files, draft or released (requirement 8.1). The versions started from
    it keep going, their base cleared (8.2), and the firmware's others are left as they are
    (8.3).

    Refused, deleting nothing, while a flash names it (15's requirement 5.1): the refusal
    carries those flashes, so the page can offer to remove each.
    """

    def __init__(self, unit_of_work: FlashUnitOfWorkFactory, clock: Clock) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    async def __call__(self, workspace_id: WorkspaceId, version_id: VersionId) -> None:
        async with self._unit_of_work(workspace_id) as work:
            # Read under the firmware's lock, which a flash takes before its insert (15's
            # decision 9), so no flash of the version is logged between this read and the delete.
            firmware, version = await lock_version(work, version_id)
            flashed = await work.flashes.of_version(version.id)
            if flashed:
                blocking = await blocking_flashes(work, flashed)
                number = str(version.number)
                raise VersionFlashedError(flashed_message(number, blocking), blocking, item=number)
            await work.versions.remove(version)
            # A deleted version leaves no date behind, so its firmware keeps the moment for the
            # list's order (requirement 2.2).
            firmware.touch(self._clock.now())
            await work.commit()


class GetVersion:
    """A version as it opens (requirement 5.8): the version, its base while that one exists,
    and its files, in three reads at most whatever their number (12.3)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId, version_id: VersionId) -> VersionView:
        async with self._unit_of_work(workspace_id) as work:
            version = await load_version(work, version_id)
            return await _view(work, version)


class VersionIsReleased:
    """Whether the version is live and released: the only kind a build is attached to, since a
    draft's source can still change under it (20-firmware-builds, decision 3). What the files
    module asks through bootstrap before an upload, so a draft reads there as no such version."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId, version_id: VersionId) -> bool:
        async with self._unit_of_work(workspace_id) as work:
            version = await work.versions.get(version_id)
            return version is not None and version.status is VersionStatus.RELEASED


class VersionIsKept:
    """Whether the workspace still holds the version, live or with its firmware in the trash:
    what the files prune asks before it sweeps a version's builds (20's 1.6, 1.7)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId, version_id: VersionId) -> bool:
        async with self._unit_of_work(workspace_id) as work:
            return await work.versions.kept(version_id)


async def load_version(work: FirmwareUnitOfWork, version_id: VersionId) -> FirmwareVersion:
    """The version, or a 404. Another workspace's id is simply not found (requirement 9.2)."""
    version = await work.versions.get(version_id)
    if version is None:
        raise VersionNotFoundError("that version doesn't exist")
    return version


async def lock_version(
    work: FirmwareUnitOfWork, version_id: VersionId
) -> tuple[Firmware, FirmwareVersion]:
    """The version's firmware with its row locked until the transaction ends, and the version,
    read for the first time after the lock (decision 8).

    Only the firmware's id is read before the lock. Read then, the version would sit in the
    session, and every later read in the transaction would hand back that copy: a release
    committed while this waited would go unseen, and a file would land in a released version.
    A version the workspace doesn't hold, or one that went, alone or with its firmware, while
    this waited for the lock, is a 404.
    """
    firmware_id = await work.versions.firmware_of(version_id)
    firmware = None if firmware_id is None else await work.firmwares.locked(firmware_id)
    if firmware is None:
        raise VersionNotFoundError("that version doesn't exist")
    return firmware, await load_version(work, version_id)


def _base_among(versions: FirmwareVersions, base_id: VersionId) -> FirmwareVersion:
    """The version a draft starts from, among its firmware's own: another firmware's, or one
    the workspace doesn't hold, is a 404 (requirement 5.9)."""
    base = versions.get(base_id)
    if base is None:
        raise VersionNotFoundError("that version isn't one of this firmware's")
    return base


async def _base_of(work: FirmwareUnitOfWork, version: FirmwareVersion) -> FirmwareVersion | None:
    """The version it was started from. Deleting a base clears `based_on` (requirement 8.2),
    so an id there always names a version that exists."""
    return None if version.based_on is None else await work.versions.get(version.based_on)


async def _view(work: FirmwareUnitOfWork, version: FirmwareVersion) -> VersionView:
    """The version as it opens: its base, then its files."""
    base = await _base_of(work, version)
    return VersionView(version, base, await work.sources.of_version(version.id))
