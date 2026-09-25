"""Attaching files to parts, and everything that follows: list, open, change, remove, prune.

Every write is one unit of work: nothing is stored unless the use case reaches `commit()`
(design §2). The order around the file store is deliberate. An upload writes the object
first and the rows second, so a crash between the two leaves an object with no row, which
the nightly prune sweeps; a removal reverses it, deleting rows in the transaction and the
object only after commit, so a crash leaves an object the prune will still catch. Either
way the store is never left promising bytes the rows deny that a caller could reach.

`files` reaches catalog and identity only through the `Subjects` and `Quotas` ports, which
`bootstrap/` implements (design §3): the module imports neither.
"""

import hashlib
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from wiredex.files.application.ports import FileStore, FilesUnitOfWork, Quotas, Subjects
from wiredex.files.domain.entities import Attachment, StoredFile
from wiredex.files.domain.errors import (
    AlreadyAttachedError,
    AttachmentNotFoundError,
    FileTooLargeError,
    QuotaExceededError,
    SubjectNotFoundError,
)
from wiredex.files.domain.values import (
    MAX_FILE_SIZE,
    AttachmentId,
    AttachmentKind,
    AttachmentTitle,
    FileSize,
    MediaType,
    Sha256,
    Subject,
    WorkspaceId,
)
from wiredex.shared_kernel.application.ports import Clock, IdGenerator

type UnitOfWorkFactory = Callable[[WorkspaceId], FilesUnitOfWork]


@dataclass(frozen=True, slots=True)
class FilesServices:
    """What the file use cases need besides their unit of work: the store, the two ports that
    reach other modules (design §3), and a clock and id source. Bundled so a use case takes a
    handful of collaborators, as identity's `LoginServices` bundles its own."""

    store: FileStore
    subjects: Subjects
    quotas: Quotas
    clock: Clock
    ids: IdGenerator


@dataclass(frozen=True, slots=True)
class Upload:
    """The bytes to attach, already bounded at the edge, plus how to label the attachment.

    `title` is optional: with none, the attachment takes the file's name (requirement 1.2).
    `kind` the caller chooses, the web suggesting one from the sniffed type (requirement 6.2).
    """

    data: bytes
    filename: str
    kind: AttachmentKind
    title: str | None = None


@dataclass(frozen=True, slots=True)
class AttachmentView:
    """An attachment read alongside its file, so a list shows the media type, size and date."""

    attachment: Attachment
    file: StoredFile


@dataclass(frozen=True, slots=True)
class OpenedAttachment:
    """An attachment, its file, and a stream of its bytes, for the content route."""

    attachment: Attachment
    file: StoredFile
    stream: AsyncIterator[bytes]


class Attach:
    """Store an upload's bytes once and attach them to a part (requirements 1.1, 1.3-1.5, 2.6).

    The checks run cheapest and most-refusing first: the subject before the bytes are read,
    the type and size before they are hashed, the quota and the duplicate before anything is
    stored, so a refused upload leaves the store and the rows exactly as they were.
    """

    def __init__(self, unit_of_work: UnitOfWorkFactory, services: FilesServices) -> None:
        self._unit_of_work = unit_of_work
        self._services = services

    async def __call__(
        self, workspace_id: WorkspaceId, subject: Subject, upload: Upload
    ) -> AttachmentView:
        services = self._services
        # The subject first: an upload to a part that isn't ours stores nothing (1.5).
        if not await services.subjects.exists(workspace_id, subject):
            raise SubjectNotFoundError("that part doesn't exist")
        file = _describe(upload, workspace_id, services.clock.now())
        title = _title_for(upload)

        async with self._unit_of_work(workspace_id) as work:
            existing = await work.files.get(file.sha256)
            # New bytes count against the quota; bytes already stored add nothing (2.6).
            if existing is None:
                await _check_quota(work, services.quotas, workspace_id, int(file.size))
            # Same file, same part: refused before the object is touched (1.4).
            if await work.attachments.find(subject, file.sha256) is not None:
                raise AlreadyAttachedError("that file is already attached to this part")
            # Bytes first: the object exists before any row names it (design §2). Written even
            # when a row already names these bytes: the same key and bytes overwrite
            # harmlessly, and an object lost since (a restore, a slip in the bucket) comes
            # back when the file is uploaded again.
            await services.store.put(file.object_key, upload.data, file.media_type)
            if existing is None:
                await work.files.add(file)
            else:
                file = existing
            attachment = Attachment(
                AttachmentId(services.ids.new_id()),
                workspace_id,
                subject,
                file.sha256,
                upload.kind,
                title,
                services.clock.now(),
            )
            await work.attachments.add(attachment)
            await work.commit()
            return AttachmentView(attachment, file)


class ListAttachments:
    """A part's attachments, newest first, each with its file's media type and size (1.6)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId, subject: Subject) -> list[AttachmentView]:
        async with self._unit_of_work(workspace_id) as work:
            views: list[AttachmentView] = []
            for attachment in await work.attachments.of_subject(subject):
                file = await work.files.get(attachment.sha256)
                if file is not None:
                    views.append(AttachmentView(attachment, file))
            return views


class OpenAttachment:
    """One attachment, its file, and a stream of its bytes (requirement 3).

    404 for another workspace's attachment: the unit of work only sees this workspace's
    rows, so its id is simply not found here (requirement 3.4).
    """

    def __init__(self, unit_of_work: UnitOfWorkFactory, store: FileStore) -> None:
        self._unit_of_work = unit_of_work
        self._store = store

    async def __call__(
        self, workspace_id: WorkspaceId, attachment_id: AttachmentId
    ) -> OpenedAttachment:
        async with self._unit_of_work(workspace_id) as work:
            attachment = await _load(work, attachment_id)
            file = await work.files.get(attachment.sha256)
            if file is None:
                # A row without its file is a torn state the prune resolves; to a reader it
                # simply isn't there, and reads the same as another workspace's attachment.
                raise AttachmentNotFoundError("that attachment doesn't exist")
        # Outside the transaction: streaming bytes is slow, and the rows are already read.
        return OpenedAttachment(attachment, file, self._store.open(file.object_key))


class ChangeAttachment:
    """Rename or re-kind an attachment (requirement 4.1). Commits only when something changed,
    so a no-op edit writes nothing (the entity's `rename`/`rekind` say whether it did)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(
        self,
        workspace_id: WorkspaceId,
        attachment_id: AttachmentId,
        title: AttachmentTitle | None = None,
        kind: AttachmentKind | None = None,
    ) -> Attachment:
        async with self._unit_of_work(workspace_id) as work:
            attachment = await _load(work, attachment_id)
            changed = False
            if title is not None:
                changed = attachment.rename(title) or changed
            if kind is not None:
                changed = attachment.rekind(kind) or changed
            if changed:
                await work.commit()
            return attachment


class Detach:
    """Remove an attachment, and its file when no other attachment in the workspace uses it
    (requirement 4.2). Rows in the transaction, the object only after commit (design §2)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory, store: FileStore) -> None:
        self._unit_of_work = unit_of_work
        self._store = store

    async def __call__(self, workspace_id: WorkspaceId, attachment_id: AttachmentId) -> None:
        async with self._unit_of_work(workspace_id) as work:
            attachment = await _load(work, attachment_id)
            await work.attachments.remove(attachment)
            orphaned: StoredFile | None = None
            # After the attachment is gone: zero uses means nothing else points at the file.
            if await work.attachments.uses(attachment.sha256) == 0:
                orphaned = await work.files.get(attachment.sha256)
                if orphaned is not None:
                    await work.files.remove(orphaned)
            await work.commit()
        if orphaned is not None:
            # After commit: the row is gone, so a failed delete leaves an object the prune
            # sweeps, never a row promising bytes that aren't there.
            await self._store.delete(orphaned.object_key)


class ClearWorkspace:
    """Every attachment, file row and stored object of a workspace, for a demo reset (5.3)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory, store: FileStore) -> None:
        self._unit_of_work = unit_of_work
        self._store = store

    async def __call__(self, workspace_id: WorkspaceId) -> None:
        async with self._unit_of_work(workspace_id) as work:
            # Every file the workspace holds, gathered before any attachment is removed: an
            # attachment's file plus the ones nothing points at. Read first because `unused`
            # reads the attachments table, so a file's row must be found while its attachment
            # is still there — once the attachments go, the whole bench is cleared regardless.
            doomed = await _all_files(work)
            for subject in await work.attachments.subjects():
                for attachment in await work.attachments.of_subject(subject):
                    await work.attachments.remove(attachment)
            for file in doomed:
                await work.files.remove(file)
            await work.commit()
        # After commit: whatever is left under the workspace's prefix, row or not, goes.
        async for key in self._store.keys(f"workspaces/{workspace_id}/"):
            await self._store.delete(key)


# An upload writes its bytes before its rows, so for a moment a new object has no row. The
# prune leaves objects younger than this alone: an upload takes seconds, not an hour.
ORPHAN_GRACE = timedelta(hours=1)


class PruneOrphans:
    """The nightly sweep (requirement 4.4): attachments whose subject is gone, then file rows
    no attachment uses, then objects no file row names. Run once per workspace.

    A part's deletion leaves its attachments behind (no foreign key crosses modules), and
    this is what removes them, by asking `Subjects` which subjects still exist. Nothing is
    decided from a list read earlier: rows are checked as they are when removed, and an
    object goes only when no row names it after the rows have been swept, and it is older
    than `ORPHAN_GRACE`, so an upload running during the sweep never loses its bytes.
    """

    def __init__(
        self, unit_of_work: UnitOfWorkFactory, subjects: Subjects, store: FileStore, clock: Clock
    ) -> None:
        self._unit_of_work = unit_of_work
        self._subjects = subjects
        self._store = store
        self._clock = clock

    async def __call__(self, workspace_id: WorkspaceId) -> None:
        async with self._unit_of_work(workspace_id) as work:
            await self._detach_gone_subjects(work, workspace_id)
            # What nothing uses now, attachments just removed included: an attachment committed
            # by an upload since the sweep began keeps its file.
            for file in await work.files.unused():
                await work.files.remove(file)
            await work.commit()
        await self._remove_stray_objects(workspace_id)

    async def _detach_gone_subjects(self, work: FilesUnitOfWork, workspace_id: WorkspaceId) -> None:
        """Remove every attachment whose subject no longer exists (a deleted part, 4.4)."""
        for subject in await work.attachments.subjects():
            if not await self._subjects.exists(workspace_id, subject):
                for attachment in await work.attachments.of_subject(subject):
                    await work.attachments.remove(attachment)

    async def _remove_stray_objects(self, workspace_id: WorkspaceId) -> None:
        """Objects no row names once the rows are swept, and old enough not to be in flight."""
        async with self._unit_of_work(workspace_id) as work:
            named = {file.object_key for file in await _all_files(work)}
        cutoff = self._clock.now() - ORPHAN_GRACE
        async for key in self._store.keys(f"workspaces/{workspace_id}/"):
            if key in named:
                continue
            written = await self._store.modified_at(key)
            if written is not None and written < cutoff:
                await self._store.delete(key)


async def _all_files(work: FilesUnitOfWork) -> list[StoredFile]:
    """Every file row the workspace holds: the ones an attachment uses, plus the unused ones.

    Read from the two repositories the port exposes, so no new "list every file" method is
    needed: the files behind the workspace's attachments, unioned with those `unused` names.
    """
    by_sha: dict[Sha256, StoredFile] = {}
    for subject in await work.attachments.subjects():
        for attachment in await work.attachments.of_subject(subject):
            file = await work.files.get(attachment.sha256)
            if file is not None:
                by_sha[file.sha256] = file
    for file in await work.files.unused():
        by_sha[file.sha256] = file
    return list(by_sha.values())


def _describe(upload: Upload, workspace_id: WorkspaceId, now: datetime) -> StoredFile:
    """The file an upload's bytes make: type sniffed (2.1), size and hash from the bytes.

    Built before the transaction, so a refused type (415), an oversized (413) or an empty
    file (422) is turned away without opening a unit of work. The API caps reading at the
    limit; the size check here is the backstop for a caller that didn't.
    """
    media_type = MediaType.sniff(upload.data)
    if len(upload.data) > MAX_FILE_SIZE:
        raise FileTooLargeError("that file is larger than the 25 MB limit")
    size = FileSize(len(upload.data))
    sha256 = Sha256(hashlib.sha256(upload.data).hexdigest())
    return StoredFile(workspace_id, sha256, media_type, size, now)


def _title_for(upload: Upload) -> AttachmentTitle:
    """The chosen title, or the file's name when none is given (requirement 1.2)."""
    if upload.title is not None:
        return AttachmentTitle(upload.title)
    return AttachmentTitle.from_filename(upload.filename)


async def _load(work: FilesUnitOfWork, attachment_id: AttachmentId) -> Attachment:
    """The attachment, or a 404. Another workspace's id is simply not found (3.4)."""
    attachment = await work.attachments.get(attachment_id)
    if attachment is None:
        raise AttachmentNotFoundError("that attachment doesn't exist")
    return attachment


async def _check_quota(
    work: FilesUnitOfWork, quotas: Quotas, workspace_id: WorkspaceId, incoming: int
) -> None:
    """Refuse when accepting the new bytes would take the workspace past its quota (2.6).

    Only new bytes count: an upload whose file is already stored adds nothing, so the caller
    checks this only when the file is new. The message says how much room is left.
    """
    limit = await quotas.limit_for(workspace_id)
    used = await work.files.total_size()
    if used + incoming > limit:
        left = max(limit - used, 0)
        raise QuotaExceededError(f"not enough space: {left} bytes left of {limit}")
