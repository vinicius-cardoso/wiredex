"""The files module in PostgreSQL: one repository per port, each bound to one workspace.

Every statement filters `workspace_id` itself, ADR 0007's first gate, next to the policy on
these tables that already hides another workspace's rows. Defence in depth: the filter is
what makes a query's scope readable, and it still holds if a connection ever runs without
the setting the policies read.

`SqlAttachments` hands SQLAlchemy the mapped `Attachment` and lets the session work out the
statements. `SqlFiles` has no mapper to lean on: a `StoredFile` is a frozen, slotted value
whose identity *is* its bytes, so this repository is its mapping — it reads rows into a
`StoredFile` and writes one back as a row with Core, exactly as `SqlPinouts` does the
immutable pins (design's Components, ADR 0004).
"""

from datetime import datetime

from sqlalchemy import Integer, RowMapping, Select, String, delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from wiredex.files.domain.entities import Attachment, StoredFile
from wiredex.files.domain.values import (
    AttachmentId,
    FileSize,
    MediaType,
    Sha256,
    Subject,
    WorkspaceId,
)
from wiredex.files.infrastructure.orm import attachments, files

# `files.c.sha256` and `files.c.size` carry type decorators that decode a cell back into a
# `Sha256` and a `FileSize` on the way out. This repository is the mapping instead — it reads
# the plain string and integer and puts each back through the value object itself, as
# `SqlPinouts` does — so the columns are cast to their storage types on read, stripping the
# decorator, and `_file_of` does the wrapping. `func.sum` over the plain integer is what keeps
# an empty workspace's total a 0, not a `FileSize` the domain would refuse below its 1-byte floor.
_RAW_SHA256 = files.c.sha256.cast(String)
_RAW_SIZE = files.c.size.cast(Integer)


class SqlFiles:
    """A workspace's file rows, one per (workspace, SHA-256), read and written with Core.

    No mapper, like `SqlPinouts`: a `StoredFile` is immutable and its identity is its bytes,
    so the session has nothing to track. The `add` flushes first, for the same reason the
    pins repository does — a Core `INSERT` doesn't autoflush the way an ORM one would, so an
    attachment added later in the same unit of work would find no file for its foreign key.
    """

    def __init__(self, session: AsyncSession, workspace_id: WorkspaceId) -> None:
        self._session = session
        self._workspace_id = workspace_id

    async def get(self, sha256: Sha256) -> StoredFile | None:
        found = await self._session.execute(self._mine().where(files.c.sha256 == sha256))
        row = found.mappings().one_or_none()
        return None if row is None else self._file_of(row)

    async def add(self, file: StoredFile) -> None:
        await self._session.execute(
            insert(files).values(
                workspace_id=self._workspace_id,
                sha256=file.sha256,
                media_type=file.media_type,
                size=file.size,
                created_at=file.created_at,
            )
        )

    async def remove(self, file: StoredFile) -> None:
        # Flush first, as `SqlPinouts` does: a Core DELETE doesn't flush the pending ORM
        # delete of the attachment the way an ORM one would, so without this the file's row
        # would go while its attachment still sat in the table and the RESTRICT foreign key
        # would refuse it. `Detach` removes the attachment, then the file, in one unit of work.
        await self._session.flush()
        await self._session.execute(
            delete(files).where(
                files.c.workspace_id == self._workspace_id,
                files.c.sha256 == file.sha256,
            )
        )

    async def total_size(self) -> int:
        """The sum of the workspace's file sizes, which a quota is checked against (2.6).

        Summed over the plain integer, not the decorated column: an empty workspace's total is
        a 0, which `FileSize` would refuse, so the sum stays a raw `int` the quota compares.
        """
        summed = await self._session.scalar(
            select(func.coalesce(func.sum(_RAW_SIZE), 0)).where(
                files.c.workspace_id == self._workspace_id
            )
        )
        return summed or 0

    async def unused(self) -> list[StoredFile]:
        """The workspace's files no attachment points at, for removal and the prune (4.2, 4.4)."""
        found = await self._session.execute(
            self._mine().where(
                ~select(1)
                .where(
                    attachments.c.workspace_id == self._workspace_id,
                    attachments.c.sha256 == files.c.sha256,
                )
                .exists()
            )
        )
        return [self._file_of(row) for row in found.mappings()]

    def _mine(self) -> Select[tuple[str, MediaType, int, datetime]]:
        # sha256 and size are read raw (the decorator stripped) so `_file_of` wraps them; the
        # cast labels them under the column name, so the row still reads by "sha256" and "size".
        return select(
            _RAW_SHA256.label("sha256"),
            files.c.media_type,
            _RAW_SIZE.label("size"),
            files.c.created_at,
        ).where(files.c.workspace_id == self._workspace_id)

    def _file_of(self, row: RowMapping) -> StoredFile:
        """One row as a file, every cell back through the value object that validated it.

        The `workspace_id` isn't read from the row: every row this repository sees is the
        workspace's own, so the file is stamped with the one it was opened for. `media_type`
        comes back a `MediaType` already, decoded by its column's `Enum`.
        """
        return StoredFile(
            self._workspace_id,
            Sha256(row["sha256"]),
            row["media_type"],
            FileSize(row["size"]),
            row["created_at"],
        )


class SqlAttachments:
    """A workspace's attachments, mapped: the session tracks each `Attachment` it hands back."""

    def __init__(self, session: AsyncSession, workspace_id: WorkspaceId) -> None:
        self._session = session
        self._workspace_id = workspace_id

    async def get(self, attachment_id: AttachmentId) -> Attachment | None:
        # Not session.get(), which reads by primary key alone: another workspace's id has to
        # come back as nothing found, never as a row (requirement 5.1).
        found = await self._session.execute(self._mine().where(attachments.c.id == attachment_id))
        return found.scalar_one_or_none()

    async def of_subject(self, subject: Subject) -> list[Attachment]:
        """The subject's attachments, newest first: the order the index carries (1.6)."""
        found = await self._session.execute(
            self._mine()
            .where(
                attachments.c.subject_kind == subject.kind,
                attachments.c.subject_id == subject.id,
            )
            # created_at then id, so a tie between two attached in the same instant is stable.
            .order_by(attachments.c.created_at.desc(), attachments.c.id.desc())
        )
        return list(found.scalars())

    async def find(self, subject: Subject, sha256: Sha256) -> Attachment | None:
        """The attachment of those bytes to that subject, or None: what a re-attach checks (1.4)."""
        found = await self._session.execute(
            self._mine().where(
                attachments.c.subject_kind == subject.kind,
                attachments.c.subject_id == subject.id,
                attachments.c.sha256 == sha256,
            )
        )
        return found.scalar_one_or_none()

    async def add(self, attachment: Attachment) -> None:
        self._session.add(attachment)

    async def remove(self, attachment: Attachment) -> None:
        await self._session.delete(attachment)
        # Flushed at once: `uses` and `SqlFiles.unused` are Core queries, which SQLAlchemy
        # doesn't autoflush before, so without this they would still count the attachment
        # just removed, and `Detach` and the prune would keep a file nothing uses.
        await self._session.flush()

    async def uses(self, sha256: Sha256) -> int:
        """How many attachments point at those bytes, so a detach knows to keep the file (4.2)."""
        counted = await self._session.scalar(
            select(func.count())
            .select_from(attachments)
            .where(
                attachments.c.workspace_id == self._workspace_id,
                attachments.c.sha256 == sha256,
            )
        )
        return counted or 0

    async def subjects(self) -> set[Subject]:
        """Every subject the workspace's attachments name, for the prune to test each once (4.4)."""
        found = await self._session.execute(
            select(attachments.c.subject_kind, attachments.c.subject_id)
            .where(attachments.c.workspace_id == self._workspace_id)
            .distinct()
        )
        return {Subject(kind, subject_id) for kind, subject_id in found.tuples()}

    def _mine(self) -> Select[tuple[Attachment]]:
        return select(Attachment).where(attachments.c.workspace_id == self._workspace_id)
