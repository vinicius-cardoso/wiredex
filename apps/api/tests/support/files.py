"""In-memory stand-ins for the files ports, shared by the use-case tests.

Each repository is one workspace's rows, because that is what a real files unit of work sees
(ADR 0007): the workspace it was opened for is recorded rather than filtered on, so a test
can still assert that a use case scoped itself to the caller's bench. `InMemoryFileStore`
counts every object it holds, which is how a test checks that the same bytes are one file.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import TracebackType
from typing import Self
from uuid import uuid4, uuid7

from support.identity import ManualClock, NewIds
from wiredex.files.api.router import FilesUseCases
from wiredex.files.application.attachments import (
    Attach,
    ChangeAttachment,
    ClearWorkspace,
    Detach,
    FilesServices,
    ListAttachments,
    OpenAttachment,
    PruneOrphans,
)
from wiredex.files.domain.entities import Attachment, StoredFile
from wiredex.files.domain.values import (
    AttachmentId,
    MediaType,
    Sha256,
    Subject,
    SubjectKind,
    WorkspaceId,
)

NOW = datetime(2026, 9, 25, 10, 0, tzinfo=UTC)
BENCH = WorkspaceId(uuid7())


class InMemoryFileStore:
    """The bytes, keyed as the real store keys them, counting the objects it holds.

    Not per-workspace, like the real store: a key already carries its workspace prefix. The
    count is what property 2 checks — the same bytes written twice under one key stay one
    object.
    """

    def __init__(self, clock: ManualClock | None = None) -> None:
        self.objects: dict[str, bytes] = {}
        # The content type each object was put with, so a test can check it was carried.
        self.content_types: dict[str, MediaType] = {}
        # When each object was written, on the test's clock, for the prune's grace period.
        self.written_at: dict[str, datetime] = {}
        self._clock = clock or ManualClock(NOW)

    async def put(self, key: str, data: bytes, media_type: MediaType) -> None:
        self.objects[key] = data
        self.content_types[key] = media_type
        self.written_at[key] = self._clock.now()

    async def modified_at(self, key: str) -> datetime | None:
        return self.written_at.get(key) if key in self.objects else None

    async def open(self, key: str) -> AsyncIterator[bytes]:
        yield self.objects[key]

    async def delete(self, key: str) -> None:
        # Missing is fine: removal stays idempotent, so a torn state resolves cleanly.
        self.objects.pop(key, None)

    async def keys(self, prefix: str) -> AsyncIterator[str]:
        for key in list(self.objects):
            if key.startswith(prefix):
                yield key


class InMemoryAttachments:
    """One workspace's attachments, keyed by id."""

    def __init__(self) -> None:
        self.saved: dict[AttachmentId, Attachment] = {}

    async def get(self, attachment_id: AttachmentId) -> Attachment | None:
        return self.saved.get(attachment_id)

    async def of_subject(self, subject: Subject) -> list[Attachment]:
        mine = [a for a in self.saved.values() if a.subject == subject]
        # Newest first (requirement 1.6); created_at then id keeps a stable order at a tie.
        return sorted(mine, key=lambda a: (a.created_at, a.id), reverse=True)

    async def find(self, subject: Subject, sha256: Sha256) -> Attachment | None:
        return next(
            (a for a in self.saved.values() if a.subject == subject and a.sha256 == sha256),
            None,
        )

    async def add(self, attachment: Attachment) -> None:
        self.saved[attachment.id] = attachment

    async def remove(self, attachment: Attachment) -> None:
        del self.saved[attachment.id]

    async def uses(self, sha256: Sha256) -> int:
        return sum(1 for a in self.saved.values() if a.sha256 == sha256)

    async def subjects(self) -> set[Subject]:
        return {a.subject for a in self.saved.values()}


class InMemoryFiles:
    """One workspace's file rows, keyed by their SHA-256."""

    def __init__(self, attachments: InMemoryAttachments) -> None:
        self.saved: dict[Sha256, StoredFile] = {}
        # `unused` needs to know which files an attachment still points at.
        self._attachments = attachments

    async def get(self, sha256: Sha256) -> StoredFile | None:
        return self.saved.get(sha256)

    async def add(self, file: StoredFile) -> None:
        self.saved[file.sha256] = file

    async def remove(self, file: StoredFile) -> None:
        del self.saved[file.sha256]

    async def total_size(self) -> int:
        return sum(int(file.size) for file in self.saved.values())

    async def unused(self) -> list[StoredFile]:
        used = {a.sha256 for a in self._attachments.saved.values()}
        return [file for file in self.saved.values() if file.sha256 not in used]


class InMemoryFilesUnitOfWork:
    """A unit of work over shared in-memory stores; counts commits and who it was opened for."""

    def __init__(self) -> None:
        self.attachments = InMemoryAttachments()
        self.files = InMemoryFiles(self.attachments)
        self.commits = 0
        self.opened_for: list[WorkspaceId] = []

    def for_workspace(self, workspace_id: WorkspaceId) -> Self:
        """The `UnitOfWorkFactory` a use case takes, recording the bench it asked for."""
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


class FakeSubjects:
    """The `Subjects` port over a set of subjects known to exist, per workspace."""

    def __init__(self) -> None:
        self.existing: set[tuple[WorkspaceId, Subject]] = set()

    def add(self, workspace_id: WorkspaceId, subject: Subject) -> None:
        self.existing.add((workspace_id, subject))

    def drop(self, workspace_id: WorkspaceId, subject: Subject) -> None:
        """What a deleted part does: the subject stops existing, for the prune to catch."""
        self.existing.discard((workspace_id, subject))

    async def exists(self, workspace_id: WorkspaceId, subject: Subject) -> bool:
        return (workspace_id, subject) in self.existing


class FakeQuotas:
    """The `Quotas` port over a per-workspace limit, big enough not to bite unless set.

    `limit` is the default every workspace gets; a test sets `for_workspace[id]` to give one
    bench a tighter quota, which is also what proves the limit is read per workspace (2.7).
    """

    def __init__(self, limit: int = 5 * 1024 * 1024 * 1024) -> None:
        self.limit = limit
        self.for_workspace: dict[WorkspaceId, int] = {}

    async def limit_for(self, workspace_id: WorkspaceId) -> int:
        return self.for_workspace.get(workspace_id, self.limit)


class World:
    """The files use cases over in-memory fakes, with one part that exists and a quota.

    The seed subject is a part that already exists in `BENCH`, so an `Attach` in a test finds
    it without going through the catalog. The quota is generous by default; a test tightens it
    on `quotas.limit` to exercise requirement 2.6.
    """

    def __init__(self) -> None:
        self.work = InMemoryFilesUnitOfWork()
        self.clock = ManualClock(NOW)
        self.store = InMemoryFileStore(self.clock)
        self.subjects = FakeSubjects()
        self.quotas = FakeQuotas()
        self.ids = NewIds()
        self.part = Subject(SubjectKind.PART, uuid4())
        self.subjects.add(BENCH, self.part)
        work = self.work.for_workspace
        services = FilesServices(self.store, self.subjects, self.quotas, self.clock, self.ids)
        self.attach = Attach(work, services)
        self.list_attachments = ListAttachments(work)
        self.open_attachment = OpenAttachment(work, self.store)
        self.change_attachment = ChangeAttachment(work)
        self.detach = Detach(work, self.store)
        self.clear_workspace = ClearWorkspace(work, self.store)
        self.prune = PruneOrphans(work, self.subjects, self.store, self.clock)

    def files_use_cases(self) -> FilesUseCases:
        """What `create_router` takes, so the API test mounts these same in-memory fakes."""
        return FilesUseCases(
            attach=self.attach,
            list_attachments=self.list_attachments,
            open_attachment=self.open_attachment,
            change_attachment=self.change_attachment,
            detach=self.detach,
            clear_workspace=self.clear_workspace,
            prune_orphans=self.prune,
        )

    def another_part(self) -> Subject:
        """A second part in the same bench, so a test can attach the same file to two parts."""
        subject = Subject(SubjectKind.PART, uuid4())
        self.subjects.add(BENCH, subject)
        return subject

    def a_missing_part(self) -> Subject:
        """A part id no `Subjects.exists` knows: an upload to it is a 404 (requirement 1.5)."""
        return Subject(SubjectKind.PART, uuid4())
