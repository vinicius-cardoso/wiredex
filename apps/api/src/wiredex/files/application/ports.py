"""What the files use cases need from the outside, as Protocols over domain types.

Two of these ports reach across a module boundary that `files` never imports directly
(design §3): `Subjects` asks whether a part exists (catalog answers), and `Quotas` asks how
many bytes a workspace may store (identity answers). `bootstrap/` implements both, so the
module stays independent while a use case can still refuse an upload to a missing part.

The repository ports, `Files` and `Attachments`, take no workspace: the unit of work is
built for one workspace and its repositories only ever see that workspace's rows (ADR 0007),
which is why `FilesUnitOfWork` exposes them as read-only properties. `FileStore` is the one
port that isn't per-workspace: an object key already carries the workspace prefix, so a
single store serves every bench.
"""

from collections.abc import AsyncIterator
from typing import Protocol

from wiredex.files.domain.entities import Attachment, StoredFile
from wiredex.files.domain.values import (
    AttachmentId,
    MediaType,
    Sha256,
    Subject,
    WorkspaceId,
)
from wiredex.shared_kernel.application.ports import UnitOfWork


class FileStore(Protocol):
    """The bytes, keyed by `StoredFile.object_key`. Not per-workspace: the key is the scope."""

    async def put(self, key: str, data: bytes, media_type: MediaType) -> None:
        """Writes the object. Idempotent: the same key and bytes may be written again."""
        ...

    def open(self, key: str) -> AsyncIterator[bytes]:
        """The object's bytes, streamed in chunks so a large file never sits in memory whole.

        Not `async def`: an implementation is an async generator, whose *call* already returns
        the iterator (no `await`), the same shape as `keys`.
        """
        ...

    async def delete(self, key: str) -> None:
        """Deletes the object. A key that isn't there is fine, so removal stays idempotent."""
        ...

    def keys(self, prefix: str) -> AsyncIterator[str]:
        """Every object key under the prefix, for the prune to find objects no row names."""
        ...


class Files(Protocol):
    """A workspace's file rows, one per (workspace, SHA-256)."""

    async def get(self, sha256: Sha256) -> StoredFile | None: ...

    async def add(self, file: StoredFile) -> None: ...

    async def remove(self, file: StoredFile) -> None: ...

    async def total_size(self) -> int:
        """The sum of the workspace's stored file sizes, which a quota is checked against."""
        ...

    async def unused(self) -> list[StoredFile]:
        """The workspace's files no attachment points at, for removal and the prune."""
        ...


class Attachments(Protocol):
    """A workspace's attachments, each a file attached to a subject with a kind and a title."""

    async def get(self, attachment_id: AttachmentId) -> Attachment | None: ...

    async def of_subject(self, subject: Subject) -> list[Attachment]:
        """The subject's attachments, newest first (requirement 1.6)."""
        ...

    async def find(self, subject: Subject, sha256: Sha256) -> Attachment | None:
        """The attachment of those bytes to that subject, or None: what a re-attach checks (1.4)."""
        ...

    async def add(self, attachment: Attachment) -> None: ...

    async def remove(self, attachment: Attachment) -> None: ...

    async def uses(self, sha256: Sha256) -> int:
        """How many attachments point at those bytes, so a detach knows to keep the file (4.2)."""
        ...

    async def subjects(self) -> set[Subject]:
        """Every subject the workspace's attachments name, for the prune to test each once."""
        ...


class Subjects(Protocol):
    """Whether a subject exists, answered outside the module (catalog's `GetPart`, design §3)."""

    async def exists(self, workspace_id: WorkspaceId, subject: Subject) -> bool: ...


class Quotas(Protocol):
    """A workspace's storage quota in bytes, answered from its kind (design §3)."""

    async def limit_for(self, workspace_id: WorkspaceId) -> int: ...


class FilesUnitOfWork(UnitOfWork, Protocol):
    # Read-only properties, not attributes: a protocol attribute would have to match
    # exactly, so SqlFiles wouldn't count as Files (as CatalogUnitOfWork does it).
    @property
    def files(self) -> Files: ...

    @property
    def attachments(self) -> Attachments: ...
