"""The two things the module stores: a file's bytes, and an attachment that points at them.

A `StoredFile` is the bytes, addressed by their SHA-256 within a workspace; the same bytes
uploaded twice are one file. An `Attachment` is a file attached to a subject with a kind and
a title; two parts may attach the same file. Both stay plain Python: nothing here imports a
framework, and persistence maps these classes imperatively (ADR 0004).
"""

from dataclasses import dataclass
from datetime import datetime

from wiredex.files.domain.values import (
    AttachmentId,
    AttachmentKind,
    AttachmentTitle,
    FileSize,
    MediaType,
    Sha256,
    Subject,
    WorkspaceId,
)


@dataclass(frozen=True, slots=True)
class StoredFile:
    """Bytes in the file store, named by their content: one row per (workspace, SHA-256).

    Immutable, because its identity *is* its bytes: nothing about a file changes once it is
    stored, so a re-upload of the same bytes finds this row and adds no second copy
    (requirement 1.3).
    """

    workspace_id: WorkspaceId
    sha256: Sha256
    media_type: MediaType
    size: FileSize
    created_at: datetime

    @property
    def object_key(self) -> str:
        """Where the bytes live in the store: `workspaces/<workspace_id>/sha256/<hex>`.

        The workspace prefix keeps two workspaces from ever sharing an object, so a demo
        reset can delete a prefix without touching anyone else's files and one workspace
        can't probe whether a file exists in another (requirement 5.2).
        """
        return f"workspaces/{self.workspace_id}/sha256/{self.sha256}"


@dataclass(eq=False)
class Attachment:
    """A file attached to a subject, with a kind and a title the owner can change.

    Mutable where a file is not: `rename` and `rekind` change the label, never the bytes, and
    each returns whether it changed anything so a no-op update commits nothing.
    """

    id: AttachmentId
    workspace_id: WorkspaceId
    subject: Subject
    sha256: Sha256
    kind: AttachmentKind
    title: AttachmentTitle
    created_at: datetime

    def rename(self, title: AttachmentTitle) -> bool:
        """Gives the attachment a new title. Returns whether the title actually changed."""
        if self.title == title:
            return False
        self.title = title
        return True

    def rekind(self, kind: AttachmentKind) -> bool:
        """Changes what kind of attachment this is. Returns whether the kind actually changed."""
        if self.kind == kind:
            return False
        self.kind = kind
        return True
