"""Tables for the files module, mapped imperatively onto the plain domain classes.

Tables of workspace data, so both carry a `workspace_id` and their migration turns
row-level security on for them (ADR 0007, design's Data Models). The domain classes stay
plain Python; the mapping lives here (ADR 0001, ADR 0004).

`files` is content-addressed: one row per `(workspace_id, sha256)`, so the same bytes
uploaded twice are one file. `attachments` points at that pair, not at `part_definitions`:
modules don't reach into each other's tables, and the nightly prune covers deleted parts.

`attachments` is mapped imperatively onto the mutable `Attachment`. `files` has no mapper:
`StoredFile` is a frozen, slotted value whose identity *is* its bytes, so `SqlFiles` reads
and writes it with Core, exactly as `SqlPinouts` does the immutable `pins` (design's
Components, ADR 0004). The type decorators below still serve both, so the Core statements
speak in the same value objects.
"""

from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    ForeignKeyConstraint,
    Index,
    PrimaryKeyConstraint,
    Table,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import composite

from wiredex.files.domain.entities import Attachment
from wiredex.files.domain.values import (
    MAX_FILE_SIZE,
    AttachmentKind,
    MediaType,
    Subject,
    SubjectKind,
)
from wiredex.files.infrastructure.types import (
    AttachmentTitleType,
    FileSizeType,
    Sha256Type,
)
from wiredex.shared_kernel.infrastructure.orm import mapper_registry, metadata


def _enum(enum: type[StrEnum], name: str, length: int) -> Enum:
    # Text with a CHECK constraint, never a Postgres enum type, as the catalog does: one more
    # media type or kind is then a simple migration instead of an ALTER TYPE.
    return Enum(
        enum,
        name=name,
        native_enum=False,
        create_constraint=True,
        values_callable=lambda members: [member.value for member in members],
        length=length,
    )


files = Table(
    "files",
    metadata,
    Column("workspace_id", Uuid, nullable=False),
    # The lower-case hex SHA-256 of the bytes: fixed 64 characters.
    Column("sha256", Sha256Type, nullable=False),
    Column("media_type", _enum(MediaType, "media_type", 32), nullable=False),
    Column("size", FileSizeType, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    # Content-addressed within the workspace: the pair is the identity, so a re-upload of the
    # same bytes finds this row and adds no second copy (requirement 1.3). `attachments`
    # points at this pair, so it must be unique — the primary key makes it so.
    PrimaryKeyConstraint("workspace_id", "sha256", name="pk_files"),
    # One byte to 25 MiB, the same bounds `FileSize` validates in the domain (requirement 2.4).
    CheckConstraint(f"size BETWEEN 1 AND {MAX_FILE_SIZE}", name="size_in_range"),
)

attachments = Table(
    "attachments",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("workspace_id", Uuid, nullable=False, index=True),
    Column("subject_kind", _enum(SubjectKind, "subject_kind", 16), nullable=False),
    Column("subject_id", Uuid, nullable=False),
    Column("sha256", Sha256Type, nullable=False),
    Column("kind", _enum(AttachmentKind, "attachment_kind", 16), nullable=False),
    Column("title", AttachmentTitleType, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    # The pair, not `sha256` alone: Postgres checks foreign keys without row-level security,
    # so this keeps an attachment's file in its own workspace, as the pins' key keeps a pin
    # with its part (ADR 0007). RESTRICT, because a file with attachments is never orphaned:
    # `Detach` removes the file row only once nothing uses it.
    ForeignKeyConstraint(
        ["workspace_id", "sha256"],
        ["files.workspace_id", "files.sha256"],
        name="fk_attachments_workspace_id_files",
        ondelete="RESTRICT",
    ),
    # The same file attached twice to the same subject is refused with 409 (requirement 1.4).
    UniqueConstraint(
        "workspace_id", "subject_kind", "subject_id", "sha256", name="uq_attachments_subject"
    ),
    # Listing a subject's attachments newest first (requirement 1.6): the index carries the
    # order, so the query reads it straight off.
    Index(
        "ix_attachments_subject",
        "workspace_id",
        "subject_kind",
        "subject_id",
        text("created_at DESC"),
    ),
)


mapper_registry.map_imperatively(
    Attachment,
    attachments,
    properties={
        # `Subject` is a kind + id pair; the two columns compose it and split it apart again,
        # in the order the frozen dataclass takes them (kind, id).
        "subject": composite(Subject, attachments.c.subject_kind, attachments.c.subject_id),
    },
)
