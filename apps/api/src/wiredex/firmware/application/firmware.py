"""Firmware: create one, edit it, delete it, open it, list them, and list a revision's.

Every write locks the firmware's row first (decision 8), so writes to one firmware, its links,
its versions and their files take turns. A write that answers a page reads it before its
commit, since the workspace setting row-level security reads ends with the transaction
(ADR 0007).

The revisions a firmware runs on are resolved at every read through the directory (decision
3): a link whose revision the workspace no longer holds is left out of the answer, kept, and
refuses nothing.

A firmware or a version a flash names stays (15-flash-log decision 6). The read that names the
flashes in the way serves both deletes, so it lives here: `versions.py` imports from this file,
and `flashes.py` from `versions.py`, so neither of them can hold it without an import cycle.
"""

from collections.abc import Callable, Mapping, Sequence

from wiredex.firmware.application.ports import (
    FirmwareSummary,
    FirmwareUnitOfWork,
    FirmwareView,
    FlashEntry,
    FlashUnitOfWork,
    RevisionFacts,
    RunsOnUnitOfWork,
    VersionSummary,
)
from wiredex.firmware.domain.errors import (
    FirmwareFlashedError,
    FirmwareNotFoundError,
    NameTakenError,
    RevisionNotFoundError,
)
from wiredex.firmware.domain.firmware import Firmware, FirmwareDetails
from wiredex.firmware.domain.flash import BlockingFlash
from wiredex.firmware.domain.semver import FIRST_VERSION
from wiredex.firmware.domain.values import FirmwareId, FirmwareName, RevisionId, WorkspaceId
from wiredex.firmware.domain.version import FirmwareVersions, VersionStatus
from wiredex.shared_kernel.application.ports import Clock, IdGenerator

type UnitOfWorkFactory = Callable[[WorkspaceId], FirmwareUnitOfWork]
type RunsOnUnitOfWorkFactory = Callable[[WorkspaceId], RunsOnUnitOfWork]
type FlashUnitOfWorkFactory = Callable[[WorkspaceId], FlashUnitOfWork]


class CreateFirmware:
    """A firmware with no versions (requirement 1.1) and, when it is created for a revision, its
    link to that revision in the same transaction (3.3)."""

    def __init__(
        self, unit_of_work: RunsOnUnitOfWorkFactory, clock: Clock, ids: IdGenerator
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._ids = ids

    async def __call__(
        self,
        workspace_id: WorkspaceId,
        details: FirmwareDetails,
        revision_id: RevisionId | None = None,
    ) -> FirmwareView:
        async with self._unit_of_work(workspace_id) as work:
            # The revision before the name: a firmware for a revision that went is a 404,
            # whatever it is called.
            revision = None if revision_id is None else await load_revision(work, revision_id)
            await _check_name_free(work, details.name)
            now = self._clock.now()
            firmware = Firmware.start(FirmwareId(self._ids.new_id()), workspace_id, details, now)
            await work.firmwares.add(firmware)
            if revision is not None:
                await work.links.add(firmware.id, revision.revision_id, now)
            await work.commit()
            runs_on = () if revision is None else (revision,)
            return FirmwareView(firmware, (), runs_on, None, FIRST_VERSION)


class UpdateFirmware:
    """Replaces a firmware's name, target, framework and description whole (requirement 1.7);
    the details it already has write nothing."""

    def __init__(self, unit_of_work: RunsOnUnitOfWorkFactory, clock: Clock) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    async def __call__(
        self, workspace_id: WorkspaceId, firmware_id: FirmwareId, details: FirmwareDetails
    ) -> FirmwareView:
        async with self._unit_of_work(workspace_id) as work:
            firmware = await lock_firmware(work, firmware_id)
            # Only a new name can be another firmware's.
            if details.name != firmware.name:
                await _check_name_free(work, details.name, keeping=firmware)
            changed = firmware.revise(details, self._clock.now())
            view = await _page(work, firmware)
            if changed:
                await work.commit()
            return view


class DeleteFirmware:
    """A firmware with its versions, their files and its links, in one transaction (1.9).

    Refused, deleting nothing, while a flash names one of its versions (15's requirement 5.2):
    the refusal carries those flashes, so the page can offer to remove each.
    """

    def __init__(self, unit_of_work: FlashUnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId, firmware_id: FirmwareId) -> None:
        async with self._unit_of_work(workspace_id) as work:
            # Locked as every write is, so no version or file is written while it goes, and no
            # flash is logged: a flash takes this lock before its insert (15's decision 9).
            firmware = await lock_firmware(work, firmware_id)
            flashed = await work.flashes.of_firmware(firmware.id)
            if flashed:
                blocking = await blocking_flashes(work, flashed)
                raise FirmwareFlashedError(
                    flashed_message(str(firmware.name), blocking), blocking, item=str(firmware.name)
                )
            await work.firmwares.remove(firmware)
            await work.commit()


class GetFirmware:
    """A firmware's page in four reads at most, whatever its numbers of versions, files and
    links (requirements 1.8, 12.3)."""

    def __init__(self, unit_of_work: RunsOnUnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId, firmware_id: FirmwareId) -> FirmwareView:
        async with self._unit_of_work(workspace_id) as work:
            firmware = await load_firmware(work, firmware_id)
            return await _page(work, firmware)


class ListFirmware:
    """The firmware whose name or target holds a text, last changed first, in two reads at most
    whatever their number (requirements 2.1 to 2.4, 12.3)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(
        self, workspace_id: WorkspaceId, text: str | None = None
    ) -> list[FirmwareSummary]:
        # A search box cleared to spaces asks for nothing, as the project list's does.
        wanted = (text or "").strip()
        async with self._unit_of_work(workspace_id) as work:
            return await _summaries(work, await work.firmwares.matching(wanted))


class ListRevisionFirmware:
    """The firmware a revision runs, by name (requirement 3.4), in three reads at most whatever
    their number (12.3). A revision the workspace doesn't hold is a 404 (3.7), even one that
    firmware still links to (decision 3)."""

    def __init__(self, unit_of_work: RunsOnUnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(
        self, workspace_id: WorkspaceId, revision_id: RevisionId
    ) -> list[FirmwareSummary]:
        async with self._unit_of_work(workspace_id) as work:
            await load_revision(work, revision_id)
            return await _summaries(work, await work.firmwares.running_on(revision_id))


async def load_firmware(work: FirmwareUnitOfWork, firmware_id: FirmwareId) -> Firmware:
    """The firmware, or a 404. Another workspace's id is simply not found (requirement 9.2)."""
    firmware = await work.firmwares.get(firmware_id)
    if firmware is None:
        raise FirmwareNotFoundError("that firmware doesn't exist")
    return firmware


async def lock_firmware(work: FirmwareUnitOfWork, firmware_id: FirmwareId) -> Firmware:
    """The firmware with its row locked until the transaction ends, or a 404 (decision 8).

    Every write takes it before it reads anything else of the firmware, so writes to one
    firmware take turns and each reads what the one before it committed.
    """
    firmware = await work.firmwares.locked(firmware_id)
    if firmware is None:
        raise FirmwareNotFoundError("that firmware doesn't exist")
    return firmware


async def load_revision(work: RunsOnUnitOfWork, revision_id: RevisionId) -> RevisionFacts:
    """The revision as the directory names it, or a 404 (requirement 3.7): the directory holds
    neither another workspace's revision nor a deleted one.

    Nothing locks it (decision 5). A revision deleted by another request after this check
    leaves a link the reads already leave out.
    """
    revision = (await work.revisions.refs([revision_id])).get(revision_id)
    if revision is None:
        raise RevisionNotFoundError("that revision doesn't exist")
    return revision


async def blocking_flashes(
    work: FlashUnitOfWork, entries: Sequence[FlashEntry]
) -> tuple[BlockingFlash, ...]:
    """The flashes keeping a version or a firmware from being deleted, in the order they came,
    each saying whether inventory still holds its unit (15's decision 6), read in one go.

    A retired unit is still held, so its page is linked; a deleted one isn't, and its entry is
    still offered for removal, since its page is gone.
    """
    present = await work.units.facts(list(dict.fromkeys(entry.flash.unit_id for entry in entries)))
    return tuple(
        BlockingFlash(entry.flash, entry.number, entry.flash.unit_id in present)
        for entry in entries
    )


def flashed_message(subject: str, blocking: Sequence[BlockingFlash]) -> str:
    """`1.0.0 is in the flash log of WX-U-0002; …`, naming the board when there is one and
    counting them when there are more, as a part on several bills of materials is counted."""
    codes = list(dict.fromkeys(str(entry.flash.unit_code) for entry in blocking))
    boards = codes[0] if len(codes) == 1 else f"{len(codes)} boards"
    logs = "log" if len(codes) == 1 else "logs"
    return f"{subject} is in the flash {logs} of {boards}; remove those entries to delete it"


async def _check_name_free(
    work: FirmwareUnitOfWork, name: FirmwareName, keeping: Firmware | None = None
) -> None:
    """Requirement 1.3, the refusal naming the firmware that holds the name. A firmware renamed
    to its own name in another case still holds it, so `keeping` is never in its own way."""
    holder = await work.firmwares.named(name)
    if holder is not None and (keeping is None or holder.id != keeping.id):
        raise NameTakenError(f"there is already a firmware named {holder.name}", item=str(name))


async def _page(work: RunsOnUnitOfWork, firmware: Firmware) -> FirmwareView:
    """The firmware's versions with their summaries, then its links, then the revisions they
    name: three reads after the firmware's own whatever the numbers (decision 12), and no
    question to the directory when nothing is linked."""
    summaries = (await work.versions.summaries([firmware.id])).get(firmware.id, ())
    linked = await work.links.of_firmware(firmware.id)
    held = await work.revisions.refs(linked) if linked else {}
    versions = FirmwareVersions.of(summary.version for summary in summaries)
    return FirmwareView(
        firmware=firmware,
        versions=summaries,
        runs_on=_resolved(linked, held),
        latest_release=versions.latest_release,
        suggested=versions.suggested(),
    )


def _resolved(
    linked: Sequence[RevisionId], held: Mapping[RevisionId, RevisionFacts]
) -> tuple[RevisionFacts, ...]:
    """The linked revisions the workspace still holds, in link order (requirements 3.5, 3.6)."""
    return tuple(held[revision_id] for revision_id in linked if revision_id in held)


async def _summaries(
    work: FirmwareUnitOfWork, firmware: Sequence[Firmware]
) -> list[FirmwareSummary]:
    """A list's rows in the order the firmware came, their versions read in one aggregate, and
    none for an empty list."""
    ids = [one.id for one in firmware]
    summaries = await work.versions.summaries(ids) if ids else {}
    return [_summary(one, summaries.get(one.id, ())) for one in firmware]


def _summary(firmware: Firmware, summaries: Sequence[VersionSummary]) -> FirmwareSummary:
    """A row: the latest release, which a draft above it doesn't hide, and how many versions
    and drafts the firmware has (requirements 2.1, 3.4)."""
    versions = FirmwareVersions.of(summary.version for summary in summaries)
    return FirmwareSummary(
        firmware=firmware,
        latest_release=versions.latest_release,
        versions=len(versions.items),
        drafts=sum(1 for version in versions.items if version.status is VersionStatus.DRAFT),
    )
