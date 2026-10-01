"""The flash log (15-flash-log): log a flash, read what a board runs, remove an entry, and list
the boards a firmware runs on.

A flash locks its version's firmware before its unit (decision 9). The deletes of 13 take the
same firmware lock before they look for flashes, so no version goes between a flash's check
and its insert; nothing takes a unit's lock before a firmware's, so no two writers wait on
each other in a circle. The unit is locked as 06's retire and delete lock it, so they take
turns (requirement 1.11), and `lock` is its first read in the transaction, which is what lets
it read what the retire committed.

The revisions a flash recorded, and those holding the boards now, are resolved at every read,
as a firmware's links are (13's decision 3): a revision the workspace no longer holds is left
out of the answer, and the flash keeps naming it. Each read is a fixed number of statements
whatever the numbers of flashes, units and versions (decision 12, requirement 9.3), and a
read with nothing to ask asks nothing.
"""

from collections.abc import Iterable, Mapping, Sequence

from wiredex.firmware.application.firmware import (
    FlashUnitOfWorkFactory,
    UnitOfWorkFactory,
    load_firmware,
)
from wiredex.firmware.application.ports import (
    BoardView,
    FlashEntry,
    FlashUnitOfWork,
    FlashView,
    NewFlash,
    RevisionFacts,
    UnitFirmwareView,
)
from wiredex.firmware.application.versions import lock_version
from wiredex.firmware.domain.errors import FlashNotFoundError, UnitNotFoundError
from wiredex.firmware.domain.flash import Flash, FlashDetails, FlashLog
from wiredex.firmware.domain.values import FirmwareId, FlashId, RevisionId, UnitId, WorkspaceId
from wiredex.firmware.domain.version import FirmwareVersion
from wiredex.shared_kernel.application.ports import Clock, IdGenerator


class LogFlash:
    """A released version flashed onto a unit of the workspace, at the time given or now, with
    its notes (requirements 1.1 to 1.3), in one commit. It records the unit's code and the
    revision holding it now (1.7, 1.8), and answers the entry with that revision.

    A unit or a version the workspace doesn't hold is a 404, the version asked first (1.10); a
    draft, a retired unit and a time too far ahead are refused as `Flash.record` refuses them.
    """

    def __init__(
        self, unit_of_work: FlashUnitOfWorkFactory, clock: Clock, ids: IdGenerator
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._ids = ids

    async def __call__(
        self, workspace_id: WorkspaceId, unit_id: UnitId, new: NewFlash
    ) -> FlashView:
        async with self._unit_of_work(workspace_id) as work:
            firmware, version = await lock_version(work, new.version_id)
            unit = await work.units.lock(unit_id)
            if unit is None:
                raise UnitNotFoundError("that unit doesn't exist")
            details = FlashDetails(new.flashed_at, new.notes)
            now = self._clock.now()
            flash = Flash.record(FlashId(self._ids.new_id()), unit, version, details, now)
            await work.flashes.add(flash)
            entry = FlashEntry(flash, firmware.id, firmware.name, version.number)
            # Read before the commit: the workspace setting row-level security reads ends with
            # the transaction (ADR 0007).
            view = _view(entry, await _revisions(work, [flash.revision_id]))
            await work.commit()
            return view


class GetUnitFirmware:
    """What a board runs (requirement 2): its log newest first, by when each flash was done and
    then logged, each with its firmware, version and the revision it recorded; its current
    version, the newest flash's; and that firmware's newer release. A retired unit's reads as
    any unit's, saying it is retired (2.4); a unit the workspace doesn't hold is a 404 (2.5).

    Five statements at most, the workspace setting included: the unit, its flashes joined to
    their versions and firmware, the revisions they recorded, and the current firmware's
    versions (decision 12).
    """

    def __init__(self, unit_of_work: FlashUnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId, unit_id: UnitId) -> UnitFirmwareView:
        async with self._unit_of_work(workspace_id) as work:
            unit = (await work.units.facts([unit_id])).get(unit_id)
            if unit is None:
                raise UnitNotFoundError("that unit doesn't exist")
            entries = _newest_first(await work.flashes.of_unit(unit.unit_id))
            held = await _revisions(work, (entry.flash.revision_id for entry in entries))
            current = entries[0] if entries else None
            newer = None if current is None else await _newer_release(work, current)
            flashes = tuple(_view(entry, held) for entry in entries)
            return UnitFirmwareView(unit, flashes, newer)


class RemoveFlash:
    """A flash removed from its unit's log, in one commit (requirement 3.1): whatever its unit's
    status, a unit inventory no longer holds included, since inventory isn't asked. The unit's
    current version is then its newest flash left (3.2). A flash the workspace doesn't hold is a
    404 (3.3)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId, flash_id: FlashId) -> None:
        async with self._unit_of_work(workspace_id) as work:
            flash = await work.flashes.get(flash_id)
            if flash is None:
                raise FlashNotFoundError("that flash doesn't exist")
            await work.flashes.remove(flash)
            await work.commit()


class ListBoards:
    """The boards a firmware runs on (requirement 4.1): every unit whose current version is one
    of the firmware's, by code, with that flash, the revision holding the unit now and the
    firmware's newer release. Units retired, or no longer in the workspace, are left out (4.2);
    a firmware the workspace doesn't hold is a 404 (4.3).

    Six statements at most, the workspace setting included: the firmware, each unit's newest
    flash, the units, the revisions those flashes recorded and those holding the units now in
    one read, and the firmware's versions (decision 12).
    """

    def __init__(self, unit_of_work: FlashUnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId, firmware_id: FirmwareId) -> list[BoardView]:
        async with self._unit_of_work(workspace_id) as work:
            firmware = await load_firmware(work, firmware_id)
            current = await work.flashes.current_on(firmware.id)
            if not current:
                return []
            units = await work.units.facts([entry.flash.unit_id for entry in current])
            # `current_on`'s order, by code, kept; a unit gone or retired is off the bench.
            boards = [
                (units[entry.flash.unit_id], entry)
                for entry in current
                if entry.flash.unit_id in units and not units[entry.flash.unit_id].retired
            ]
            if not boards:
                return []
            # The revisions holding the units now and those their flashes recorded, often the
            # same ones, in one read.
            holding = [unit.revision_id for unit, _ in boards]
            recorded = [entry.flash.revision_id for _, entry in boards]
            held = await _revisions(work, [*holding, *recorded])
            versions = await work.versions.of_firmware(firmware.id)
            return [
                BoardView(
                    unit=unit,
                    revision=None if unit.revision_id is None else held.get(unit.revision_id),
                    current=_view(entry, held),
                    newer_release=versions.newer_than(entry.number),
                )
                for unit, entry in boards
            ]


def _newest_first(entries: Sequence[FlashEntry]) -> list[FlashEntry]:
    """The entries in `FlashLog`'s order, the domain's rather than the read's (decision 4), so
    the current version can't depend on how a repository returned the rows."""
    by_id = {entry.flash.id: entry for entry in entries}
    return [by_id[flash.id] for flash in FlashLog.of(entry.flash for entry in entries).items]


async def _revisions(
    work: FlashUnitOfWork, wanted: Iterable[RevisionId | None]
) -> Mapping[RevisionId, RevisionFacts]:
    """The named revisions the workspace holds, in one read, and no read when none is named, as
    a firmware's page asks for its links' (13's decision 12)."""
    revision_ids = list(dict.fromkeys(one for one in wanted if one is not None))
    return await work.revisions.refs(revision_ids) if revision_ids else {}


async def _newer_release(work: FlashUnitOfWork, entry: FlashEntry) -> FirmwareVersion | None:
    """The firmware's latest release when it is above the version flashed (decision 10)."""
    versions = await work.versions.of_firmware(entry.firmware_id)
    return versions.newer_than(entry.number)


def _view(entry: FlashEntry, held: Mapping[RevisionId, RevisionFacts]) -> FlashView:
    """The entry with the revision it recorded, while the workspace still holds it."""
    recorded = entry.flash.revision_id
    return FlashView(entry, None if recorded is None else held.get(recorded))
