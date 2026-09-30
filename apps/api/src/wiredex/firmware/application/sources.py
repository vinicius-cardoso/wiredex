"""A draft's source files: add a batch, edit one, remove one (decision 10).

Each write locks the version's firmware through `lock_version` and asks the version whether it
is still a draft before anything else (decision 7), so no file lands in a version after its
release commits (requirement 6.7) and the version's limits are checked over files nothing else
is changing. A write moves the version's last change and its firmware's (requirement 2.2), and
one that changes nothing commits nothing. What was sent is read with `SourceFile.parse`, so a
refusal of a file's text names the file by its path (requirement 7.5).
"""

from collections.abc import Sequence
from datetime import datetime

from wiredex.firmware.application.firmware import UnitOfWorkFactory
from wiredex.firmware.application.ports import NewSourceFile
from wiredex.firmware.application.versions import lock_version
from wiredex.firmware.domain.errors import SourceFileNotFoundError
from wiredex.firmware.domain.firmware import Firmware
from wiredex.firmware.domain.source import SourceFile, SourceFiles
from wiredex.firmware.domain.values import SourceFileId, VersionId, WorkspaceId
from wiredex.firmware.domain.version import FirmwareVersion
from wiredex.shared_kernel.application.ports import Clock, IdGenerator


class AddSourceFiles:
    """One file or several beside a draft's others, all of them or none (requirement 7.1), in
    one insert. They answer in the version's order (7.10), each under the id it keeps."""

    def __init__(self, unit_of_work: UnitOfWorkFactory, clock: Clock, ids: IdGenerator) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._ids = ids

    async def __call__(
        self, workspace_id: WorkspaceId, version_id: VersionId, files: Sequence[NewSourceFile]
    ) -> tuple[SourceFile, ...]:
        async with self._unit_of_work(workspace_id) as work:
            firmware, version = await lock_version(work, version_id)
            version.ensure_editable()
            new = [
                SourceFile.parse(SourceFileId(self._ids.new_id()), file.path, file.text)
                for file in files
            ]
            # A batch of none changes nothing, so it inserts nothing and commits nothing.
            if not new:
                return ()
            held = await work.sources.of_version(version.id)
            # The limits over the version as the batch would leave it, before anything is
            # written, so a refused batch keeps none of its files.
            after = held.adding(new)
            await work.sources.add_all(version.id, new)
            _touch(firmware, version, self._clock.now())
            await work.commit()
            added = {file.id for file in new}
            return tuple(file for file in after.items if file.id in added)


class UpdateSourceFile:
    """Replaces a draft's file's path and text whole under its id, so a rename keeps it
    (requirement 7.8, decision 10). Its own path and bytes don't count against it, and the path
    and text it already has write nothing."""

    def __init__(self, unit_of_work: UnitOfWorkFactory, clock: Clock) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    async def __call__(
        self,
        workspace_id: WorkspaceId,
        version_id: VersionId,
        file_id: SourceFileId,
        edit: NewSourceFile,
    ) -> SourceFile:
        async with self._unit_of_work(workspace_id) as work:
            firmware, version = await lock_version(work, version_id)
            version.ensure_editable()
            files = await work.sources.of_version(version.id)
            before = _file(files, file_id)
            after = SourceFile.parse(before.id, edit.path, edit.text)
            if after == before:
                return before
            # The limits over the version as the edit would leave it; only the file is written.
            files.replacing(after)
            await work.sources.update(version.id, before, after)
            _touch(firmware, version, self._clock.now())
            await work.commit()
            return after


class RemoveSourceFile:
    """Deletes one of a draft's files (requirement 7.9)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory, clock: Clock) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    async def __call__(
        self, workspace_id: WorkspaceId, version_id: VersionId, file_id: SourceFileId
    ) -> None:
        async with self._unit_of_work(workspace_id) as work:
            firmware, version = await lock_version(work, version_id)
            version.ensure_editable()
            files = await work.sources.of_version(version.id)
            await work.sources.remove(version.id, _file(files, file_id))
            _touch(firmware, version, self._clock.now())
            await work.commit()


def _file(files: SourceFiles, file_id: SourceFileId) -> SourceFile:
    """The file among the version's own, or a 404: another version's file is simply not found
    (requirement 7.11)."""
    file = files.get(file_id)
    if file is None:
        raise SourceFileNotFoundError("that file isn't in this version")
    return file


def _touch(firmware: Firmware, version: FirmwareVersion, now: datetime) -> None:
    """A file changed: the version's last change moves, and its firmware's, which orders the
    list (requirement 2.2)."""
    version.touch(now)
    firmware.touch(now)
