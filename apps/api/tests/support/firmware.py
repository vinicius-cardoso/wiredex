"""In-memory stand-ins for the firmware ports, shared by the use-case tests.

Each store is one workspace's rows, because that is what a real firmware unit of work sees
(ADR 0007): the workspace it was opened for is recorded rather than filtered on, so a test can
still assert that a use case scoped itself to the caller's bench.

The stores do what the schema does on its own: removing a firmware takes its versions, their
files and its links (the cascades), removing a version takes its files and clears every
`based_on` naming it (`SET NULL`), and neither goes while a flash names the version (the
flashes' `RESTRICT`). They read back in the order the SQL repositories promise,
write straight through and count commits, so "nothing written" is something a test can see.
The revisions a firmware runs on are named by a directory the test fills, standing in for
projects' revisions as bootstrap reads them, and the units a flash names by another, standing
in for inventory's.
"""

from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import astuple
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Self
from uuid import UUID, uuid7

from support.identity import ManualClock, NewIds
from wiredex.firmware.api.router import FirmwareUseCases
from wiredex.firmware.application.firmware import (
    CreateFirmware,
    DeleteFirmware,
    GetFirmware,
    ListFirmware,
    ListRevisionFirmware,
    UpdateFirmware,
)
from wiredex.firmware.application.flashes import (
    GetUnitFirmware,
    ListBoards,
    LogFlash,
    RemoveFlash,
)
from wiredex.firmware.application.links import CopyRevisionLinks, LinkRevision, UnlinkRevision
from wiredex.firmware.application.ports import FlashEntry, RevisionFacts, VersionSummary
from wiredex.firmware.application.sources import (
    AddSourceFiles,
    RemoveSourceFile,
    UpdateSourceFile,
)
from wiredex.firmware.application.versions import (
    DeleteVersion,
    GetVersion,
    ReleaseVersion,
    StartVersion,
    UpdateVersion,
)
from wiredex.firmware.domain.firmware import Firmware
from wiredex.firmware.domain.flash import Flash, FlashNotes, UnitCode, UnitFacts
from wiredex.firmware.domain.semver import SemVer
from wiredex.firmware.domain.source import SourceFile, SourceFiles, SourcePath, SourceText
from wiredex.firmware.domain.values import (
    BoardTarget,
    Changelog,
    FirmwareId,
    FirmwareName,
    FlashId,
    Framework,
    RevisionId,
    SourceFileId,
    UnitId,
    VersionId,
    WorkspaceId,
)
from wiredex.firmware.domain.version import FirmwareVersion, FirmwareVersions, VersionStatus
from wiredex.shared_kernel.domain.trash import TrashPosition

NOW = datetime(2026, 9, 30, 3, 0, tzinfo=UTC)
BENCH = WorkspaceId(uuid7())


class InMemorySources:
    """One workspace's source files, each under the version holding it, as `source_files`
    keeps its `version_id`."""

    def __init__(self) -> None:
        self.saved: dict[SourceFileId, tuple[VersionId, SourceFile]] = {}

    async def of_version(self, version_id: VersionId) -> SourceFiles:
        return SourceFiles.of(self.of(version_id))

    async def add_all(self, version_id: VersionId, files: Sequence[SourceFile]) -> None:
        for file in files:
            self.saved[file.id] = (version_id, file)

    async def update(self, version_id: VersionId, before: SourceFile, after: SourceFile) -> None:
        # The SQL updates the row with the file's id under the version, so both must hold.
        assert before.id == after.id
        assert self.saved[before.id] == (version_id, before)
        self.saved[after.id] = (version_id, after)

    async def remove(self, version_id: VersionId, file: SourceFile) -> None:
        assert self.saved[file.id] == (version_id, file)
        del self.saved[file.id]

    def of(self, version_id: VersionId) -> list[SourceFile]:
        return [file for held_by, file in self.saved.values() if held_by == version_id]

    def take_version(self, version_id: VersionId) -> None:
        """The cascade from a deleted version."""
        for file in self.of(version_id):
            del self.saved[file.id]


class InMemoryVersions:
    """One workspace's versions. `summaries` counts and sizes the files the sources store holds,
    as the SQL's aggregate joins them. It shares the flash store's rows, so removing a version a
    flash names fails as the database's RESTRICT does (15-flash-log decision 6)."""

    def __init__(
        self,
        sources: InMemorySources,
        flashes: Mapping[FlashId, Flash],
        firmware: Mapping[FirmwareId, Firmware] | None = None,
    ) -> None:
        self.saved: dict[VersionId, FirmwareVersion] = {}
        self._sources = sources
        self._flashes = flashes
        # The firmware store, so a version of a firmware in the trash is absent with it
        # (16-soft-delete-and-trash, decision 2).
        self._firmware: Mapping[FirmwareId, Firmware] = {} if firmware is None else firmware

    async def add(self, version: FirmwareVersion) -> None:
        self.saved[version.id] = version

    async def get(self, version_id: VersionId) -> FirmwareVersion | None:
        return self._live(version_id)

    async def firmware_of(self, version_id: VersionId) -> FirmwareId | None:
        version = self._live(version_id)
        return None if version is None else version.firmware_id

    def _live(self, version_id: VersionId) -> FirmwareVersion | None:
        version = self.saved.get(version_id)
        if version is None:
            return None
        firmware = self._firmware.get(version.firmware_id)
        return None if firmware is not None and firmware.in_trash else version

    async def of_firmware(self, firmware_id: FirmwareId) -> FirmwareVersions:
        return self._of(firmware_id)

    async def summaries(
        self, firmware_ids: Collection[FirmwareId]
    ) -> Mapping[FirmwareId, tuple[VersionSummary, ...]]:
        found: dict[FirmwareId, tuple[VersionSummary, ...]] = {}
        for firmware_id in firmware_ids:
            versions = self._of(firmware_id).items
            if versions:
                found[firmware_id] = tuple(self._summary(version) for version in versions)
        return found

    async def remove(self, version: FirmwareVersion) -> None:
        self._restrict(version)
        del self.saved[version.id]
        self._sources.take_version(version.id)
        for other in self.saved.values():
            if other.based_on == version.id:
                other.based_on = None

    def take_firmware(self, firmware_id: FirmwareId) -> None:
        """The cascade from a deleted firmware, and from its versions to their files. Every
        version based on one of them is the same firmware's, so it goes too. Refused whole,
        before anything goes, when a flash names one of them."""
        versions = self._of(firmware_id).items
        for version in versions:
            self._restrict(version)
        for version in versions:
            del self.saved[version.id]
            self._sources.take_version(version.id)

    def _restrict(self, version: FirmwareVersion) -> None:
        """The flashes' key, ON DELETE RESTRICT: a use case asks before it deletes, so reaching
        this is a use case that forgot to."""
        named = [flash.id for flash in self._flashes.values() if flash.version_id == version.id]
        assert not named, f"flashes {named} name {version.number}: the database refuses this"

    def _of(self, firmware_id: FirmwareId) -> FirmwareVersions:
        return FirmwareVersions.of(
            version for version in self.saved.values() if version.firmware_id == firmware_id
        )

    def _summary(self, version: FirmwareVersion) -> VersionSummary:
        files = self._sources.of(version.id)
        return VersionSummary(version, len(files), sum(file.text.size for file in files))


class InMemoryRevisionLinks:
    """One workspace's links, each dated when it was made.

    `copy` moves the last change of the firmware it links, as the SQL's second statement does,
    so the store shares the firmware store's rows.
    """

    def __init__(self, firmware: Mapping[FirmwareId, Firmware]) -> None:
        self.saved: dict[tuple[FirmwareId, RevisionId], datetime] = {}
        self._firmware = firmware

    async def of_firmware(self, firmware_id: FirmwareId) -> tuple[RevisionId, ...]:
        mine = sorted(
            (at, revision_id)
            for (linked, revision_id), at in self.saved.items()
            if linked == firmware_id
        )
        return tuple(revision_id for _, revision_id in mine)

    async def add(self, firmware_id: FirmwareId, revision_id: RevisionId, at: datetime) -> bool:
        if (firmware_id, revision_id) in self.saved:
            return False
        self.saved[firmware_id, revision_id] = at
        return True

    async def remove(self, firmware_id: FirmwareId, revision_id: RevisionId) -> bool:
        return self.saved.pop((firmware_id, revision_id), None) is not None

    async def copy(self, source: RevisionId, target: RevisionId, at: datetime) -> None:
        # A firmware in the trash is absent, so its link stays behind (16's requirement 2.4).
        for firmware_id in self.running_on(source):
            if self._firmware[firmware_id].in_trash:
                continue
            self.saved.setdefault((firmware_id, target), at)
            self._firmware[firmware_id].touch(at)

    def running_on(self, revision_id: RevisionId) -> list[FirmwareId]:
        return [firmware_id for firmware_id, linked in self.saved if linked == revision_id]

    def take_firmware(self, firmware_id: FirmwareId) -> None:
        """The cascade from a deleted firmware."""
        for key in [key for key in self.saved if key[0] == firmware_id]:
            del self.saved[key]


class InMemoryFirmwares:
    """One workspace's firmware. It records which firmware were locked, in order, so a test can
    tell a write took the firmware's lock (decision 8)."""

    def __init__(
        self,
        saved: dict[FirmwareId, Firmware],
        versions: InMemoryVersions,
        links: InMemoryRevisionLinks,
    ) -> None:
        self.saved = saved
        self.locks: list[FirmwareId] = []
        self._versions = versions
        self._links = links

    async def add(self, firmware: Firmware) -> None:
        self.saved[firmware.id] = firmware

    async def get(self, firmware_id: FirmwareId) -> Firmware | None:
        return self._live().get(firmware_id)

    async def locked(self, firmware_id: FirmwareId) -> Firmware | None:
        firmware = self._live().get(firmware_id)
        if firmware is not None:
            self.locks.append(firmware_id)
        return firmware

    async def named(self, name: FirmwareName) -> Firmware | None:
        holders = (one for one in self.saved.values() if one.name.fold() == name.fold())
        return next(holders, None)

    async def matching(self, text: str) -> list[Firmware]:
        # lower(), not casefold(): what PostgreSQL's ILIKE compares, so the fake and the SQL
        # agree. `in` takes % and _ as themselves, which the SQL escapes to match.
        wanted = text.lower()
        found = [
            one
            for one in self._live().values()
            if wanted in one.name.value.lower() or wanted in one.target.value.lower()
        ]
        return sorted(found, key=lambda one: (one.updated_at, one.id), reverse=True)

    async def running_on(self, revision_id: RevisionId) -> list[Firmware]:
        live = self._live()
        found = [live[key] for key in self._links.running_on(revision_id) if key in live]
        return sorted(found, key=lambda one: one.name.fold())

    async def remove(self, firmware: Firmware) -> None:
        # The versions first: a flash naming one refuses the whole delete, as it does in SQL.
        self._versions.take_firmware(firmware.id)
        del self.saved[firmware.id]
        self._links.take_firmware(firmware.id)

    async def trashed(self, before: TrashPosition | None, limit: int) -> list[Firmware]:
        held = [one for one in self._trash() if before is None or _position(one) < before]
        return sorted(held, key=_position, reverse=True)[:limit]

    async def in_trash(self, firmware_id: FirmwareId) -> Firmware | None:
        found = self.saved.get(firmware_id)
        return found if found is not None and found.in_trash else None

    async def empty_trash(self) -> int:
        trashed = self._trash()
        for firmware in trashed:
            await self.remove(firmware)
        return len(trashed)

    def _live(self) -> dict[FirmwareId, Firmware]:
        return {key: one for key, one in self.saved.items() if not one.in_trash}

    def _trash(self) -> list[Firmware]:
        return [one for one in self.saved.values() if one.in_trash]


def _position(firmware: Firmware) -> TrashPosition:
    assert firmware.trashed_at is not None  # only a firmware in the trash has a position in it
    return TrashPosition(firmware.trashed_at, firmware.id)


class InMemoryFlashes:
    """One workspace's flash log (15-flash-log). An entry reads its version's number and its
    firmware's id and name from the other stores, as the SQL joins them, and each list comes in
    the order `SqlFlashes` gives it."""

    def __init__(
        self,
        saved: dict[FlashId, Flash],
        versions: InMemoryVersions,
        firmware: Mapping[FirmwareId, Firmware],
    ) -> None:
        self.saved = saved
        self._versions = versions
        self._firmware = firmware

    async def add(self, flash: Flash) -> None:
        # The composite key: the flash names a version of its own workspace that exists.
        assert self._versions.saved[flash.version_id].workspace_id == flash.workspace_id
        self.saved[flash.id] = flash

    async def get(self, flash_id: FlashId) -> Flash | None:
        return self.saved.get(flash_id)

    async def remove(self, flash: Flash) -> None:
        del self.saved[flash.id]

    async def of_unit(self, unit_id: UnitId) -> list[FlashEntry]:
        mine = [flash for flash in self.saved.values() if flash.unit_id == unit_id]
        return [self._entry(flash) for flash in sorted(mine, key=Flash.order, reverse=True)]

    async def current_on(self, firmware_id: FirmwareId) -> list[FlashEntry]:
        newest: dict[UnitId, Flash] = {}
        for flash in self.saved.values():
            held = newest.get(flash.unit_id)
            if held is None or flash.order() > held.order():
                newest[flash.unit_id] = flash
        boards = [self._entry(flash) for flash in newest.values()]
        return sorted(
            (entry for entry in boards if entry.firmware_id == firmware_id),
            key=lambda entry: (entry.flash.unit_code.value, entry.flash.unit_id),
        )

    async def of_version(self, version_id: VersionId) -> list[FlashEntry]:
        return self._keeping(lambda entry: entry.flash.version_id == version_id)

    async def of_firmware(self, firmware_id: FirmwareId) -> list[FlashEntry]:
        return self._keeping(lambda entry: entry.firmware_id == firmware_id)

    def _keeping(self, wanted: Callable[[FlashEntry], bool]) -> list[FlashEntry]:
        """By the recorded code, then newest first: newest first, then a stable sort by code."""
        found = [entry for entry in map(self._entry, self.saved.values()) if wanted(entry)]
        found.sort(key=lambda entry: entry.flash.order(), reverse=True)
        found.sort(key=lambda entry: entry.flash.unit_code.value)
        return found

    def _entry(self, flash: Flash) -> FlashEntry:
        version = self._versions.saved[flash.version_id]
        firmware = self._firmware[version.firmware_id]
        return FlashEntry(flash, firmware.id, firmware.name, version.number)


class InMemoryRevisionDirectory:
    """Projects' revisions as firmware's `RevisionDirectory` names them, over a dict a test
    fills. Deleting an entry makes a revision the workspace no longer holds (decision 3)."""

    def __init__(self) -> None:
        self.held: dict[RevisionId, RevisionFacts] = {}
        # Each call's revision ids, so a test sees what was asked.
        self.asked: list[tuple[RevisionId, ...]] = []
        self._projects: dict[str, UUID] = {}

    async def refs(
        self, revision_ids: Collection[RevisionId]
    ) -> Mapping[RevisionId, RevisionFacts]:
        self.asked.append(tuple(revision_ids))
        return {
            revision_id: self.held[revision_id]
            for revision_id in revision_ids
            if revision_id in self.held
        }

    def hold(
        self, project: str = "Weather station", label: str = "A", summary: str | None = None
    ) -> RevisionFacts:
        """A revision of the named project, which shares its id with the project's others."""
        project_id = self._projects.setdefault(project, uuid7())
        revision = RevisionFacts(RevisionId(uuid7()), project_id, project, label, summary)
        self.held[revision.revision_id] = revision
        return revision


class InMemoryUnitDirectory:
    """Inventory's units as firmware's `UnitDirectory` names them, over a dict a test fills
    (15-flash-log decision 8). Deleting an entry makes a unit inventory no longer holds, and
    replacing one changes it, as a retire or a reservation would. It records which units were
    locked, in order, so a test can tell a flash took its unit's lock, as `InMemoryFirmwares`
    records the firmware's."""

    def __init__(self) -> None:
        self.held: dict[UnitId, UnitFacts] = {}
        self.locks: list[UnitId] = []
        self._minted = 0

    async def lock(self, unit_id: UnitId) -> UnitFacts | None:
        unit = self.held.get(unit_id)
        if unit is not None:
            self.locks.append(unit_id)
        return unit

    async def facts(self, unit_ids: Collection[UnitId]) -> Mapping[UnitId, UnitFacts]:
        return {unit_id: self.held[unit_id] for unit_id in unit_ids if unit_id in self.held}

    def hold(
        self,
        code: str | None = None,
        *,
        retired: bool = False,
        revision_id: RevisionId | None = None,
    ) -> UnitFacts:
        """A unit in the workspace, held by the revision when one is given. Its code is the next
        one inventory would mint unless given: codes are never reused, so neither are these."""
        self._minted += 1
        minted = UnitCode(f"WX-U-{self._minted:04}" if code is None else code)
        unit = UnitFacts(UnitId(uuid7()), minted, retired, revision_id)
        self.held[unit.unit_id] = unit
        return unit


class InMemoryFirmwareUnitOfWork:
    """A unit of work over shared in-memory stores; counts commits and records who it was opened
    for.

    The repositories and the directories are plain attributes, which satisfy the read-only
    properties `FlashUnitOfWork` declares. Holding `links`, it is also the
    `FirmwareRepositories` a fork's copy takes.
    """

    def __init__(self) -> None:
        firmware: dict[FirmwareId, Firmware] = {}
        flashes: dict[FlashId, Flash] = {}
        self.sources = InMemorySources()
        self.versions = InMemoryVersions(self.sources, flashes, firmware)
        self.links = InMemoryRevisionLinks(firmware)
        self.firmwares = InMemoryFirmwares(firmware, self.versions, self.links)
        self.flashes = InMemoryFlashes(flashes, self.versions, firmware)
        self.revisions = InMemoryRevisionDirectory()
        self.units = InMemoryUnitDirectory()
        self.commits = 0
        self.opened_for: list[WorkspaceId] = []

    def for_workspace(self, workspace_id: WorkspaceId) -> Self:
        """The factory a use case takes, recording the bench it asked for."""
        self.opened_for.append(workspace_id)
        return self

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def clear(self) -> None:
        # Firmware's own rows only: the revisions are projects' and the units inventory's, and
        # each clears its own. The flashes first, as the SQL's order has them.
        self.flashes.saved.clear()
        self.firmwares.saved.clear()
        self.versions.saved.clear()
        self.sources.saved.clear()
        self.links.saved.clear()


class World:
    """The firmware fakes over an empty bench, and the use cases built on them.

    Seeds are written straight to the stores, not through use cases: a test of one use case
    shouldn't depend on another one working, and only the version use cases release a version.
    """

    def __init__(self) -> None:
        self.clock = ManualClock(NOW)
        self.ids = NewIds()
        self.work = InMemoryFirmwareUnitOfWork()
        self.directory = self.work.revisions
        self.units = self.work.units
        factory = self.work.for_workspace
        self.create_firmware = CreateFirmware(factory, self.clock, self.ids)
        self.update_firmware = UpdateFirmware(factory, self.clock)
        self.delete_firmware = DeleteFirmware(factory, self.clock)
        self.get_firmware = GetFirmware(factory)
        self.list_firmware = ListFirmware(factory)
        self.list_revision_firmware = ListRevisionFirmware(factory)
        self.link_revision = LinkRevision(factory, self.clock)
        self.unlink_revision = UnlinkRevision(factory, self.clock)
        # Over the unit of work as the repositories alone, as a fork's session binds it.
        self.copy_revision_links = CopyRevisionLinks(self.work)
        self.start_version = StartVersion(factory, self.clock, self.ids)
        self.update_version = UpdateVersion(factory, self.clock)
        self.release_version = ReleaseVersion(factory, self.clock)
        self.delete_version = DeleteVersion(factory, self.clock)
        self.get_version = GetVersion(factory)
        self.add_source_files = AddSourceFiles(factory, self.clock, self.ids)
        self.update_source_file = UpdateSourceFile(factory, self.clock)
        self.remove_source_file = RemoveSourceFile(factory, self.clock)
        self.log_flash = LogFlash(factory, self.clock, self.ids)
        self.get_unit_firmware = GetUnitFirmware(factory)
        self.remove_flash = RemoveFlash(factory)
        self.list_boards = ListBoards(factory)

    def firmware_use_cases(self) -> FirmwareUseCases:
        """What `create_router` takes, so the API test mounts these same fakes."""
        return FirmwareUseCases(
            create_firmware=self.create_firmware,
            update_firmware=self.update_firmware,
            delete_firmware=self.delete_firmware,
            get_firmware=self.get_firmware,
            list_firmware=self.list_firmware,
            list_revision_firmware=self.list_revision_firmware,
            link_revision=self.link_revision,
            unlink_revision=self.unlink_revision,
            start_version=self.start_version,
            update_version=self.update_version,
            release_version=self.release_version,
            delete_version=self.delete_version,
            get_version=self.get_version,
            add_source_files=self.add_source_files,
            update_source_file=self.update_source_file,
            remove_source_file=self.remove_source_file,
            log_flash=self.log_flash,
            get_unit_firmware=self.get_unit_firmware,
            remove_flash=self.remove_flash,
            list_boards=self.list_boards,
        )

    def snapshot(self) -> tuple[object, ...]:
        """Every stored row as plain values, each firmware's and version's last change among
        them, so a later comparison sees any change: what a refused write leaves as it was."""
        work = self.work
        return (
            {key: astuple(firmware) for key, firmware in work.firmwares.saved.items()},
            {key: astuple(version) for key, version in work.versions.saved.items()},
            dict(work.sources.saved),
            dict(work.links.saved),
            dict(work.flashes.saved),
        )

    def hold_firmware(
        self,
        name: str,
        *,
        target: str = "esp32:esp32:esp32",
        framework: Framework = Framework.ARDUINO,
        minutes: int = 0,
    ) -> Firmware:
        """A firmware with no description, created and last changed `minutes` after NOW."""
        when = NOW + timedelta(minutes=minutes)
        firmware = Firmware(
            id=FirmwareId(uuid7()),
            workspace_id=BENCH,
            name=FirmwareName(name),
            target=BoardTarget(target),
            framework=framework,
            description=None,
            created_at=when,
            updated_at=when,
        )
        self.work.firmwares.saved[firmware.id] = firmware
        return firmware

    def hold_version(
        self,
        firmware: Firmware,
        number: str,
        *,
        released: bool = False,
        based_on: FirmwareVersion | None = None,
    ) -> FirmwareVersion:
        """A draft of the firmware with no changelog, or a release with one, as releasing asks
        (requirement 6.3); created, changed and released at NOW."""
        version = FirmwareVersion(
            id=VersionId(uuid7()),
            workspace_id=firmware.workspace_id,
            firmware_id=firmware.id,
            number=SemVer.parse(number),
            changelog=Changelog(f"What {number} changed.") if released else None,
            status=VersionStatus.RELEASED if released else VersionStatus.DRAFT,
            based_on=None if based_on is None else based_on.id,
            created_at=NOW,
            updated_at=NOW,
            released_at=NOW if released else None,
        )
        self.work.versions.saved[version.id] = version
        return version

    def hold_file(self, version: FirmwareVersion, path: str, text: str = "") -> SourceFile:
        file = SourceFile(SourceFileId(uuid7()), SourcePath(path), SourceText(text))
        self.work.sources.saved[file.id] = (version.id, file)
        return file

    def hold_link(self, firmware: Firmware, revision_id: RevisionId, *, minutes: int = 0) -> None:
        """A link from the firmware to the revision, made `minutes` after NOW."""
        self.work.links.saved[firmware.id, revision_id] = NOW + timedelta(minutes=minutes)

    def hold_flash(
        self,
        unit: UnitFacts,
        version: FirmwareVersion,
        *,
        flashed_at: datetime = NOW,
        logged_at: datetime | None = None,
        notes: str | None = None,
    ) -> Flash:
        """A flash of the version on the unit, logged when it was flashed unless told otherwise,
        recording the unit's code and the revision holding it, as `Flash.record` does. Written
        straight to the store, so a draft, a retired unit or a deleted one can be named, as a
        flash logged before the unit was retired or deleted is."""
        flash = Flash(
            id=FlashId(uuid7()),
            workspace_id=version.workspace_id,
            unit_id=unit.unit_id,
            unit_code=unit.code,
            version_id=version.id,
            revision_id=unit.revision_id,
            flashed_at=flashed_at,
            notes=None if notes is None else FlashNotes(notes),
            created_at=flashed_at if logged_at is None else logged_at,
        )
        self.work.flashes.saved[flash.id] = flash
        return flash
