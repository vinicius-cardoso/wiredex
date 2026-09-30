"""Firmware in PostgreSQL: one repository per port, each bound to one workspace.

Every statement filters `workspace_id` itself, the first of ADR 0007's two gates, even though
the policies on these tables already hide another workspace's rows: the filter is what makes a
query's scope readable, and what still holds if a connection ever runs without the setting the
policies read.

The firmware row is the lock that makes writes to one firmware, its links, its versions and
their files take turns (decision 8). `locked`, `get` and `of_firmware` refresh what the session
already holds, because a use case may read a row before it waits for that lock, and what it
read may have changed by the time the lock is granted. `firmware_of` reads one column, so the
version enters the session only after its firmware is locked.

Links and source files are written with Core, as projects' BOM lines and nets are: neither has
an identity worth an ORM object, and each read or write is one statement whatever the number of
rows.
"""

from collections.abc import Collection, Mapping, Sequence
from datetime import datetime
from typing import Any, cast

from sqlalchemy import (
    ColumnElement,
    DateTime,
    Select,
    Uuid,
    and_,
    delete,
    func,
    insert,
    literal,
    or_,
    select,
)
from sqlalchemy import update as update_rows
from sqlalchemy.dialects.postgresql import insert as upsert
from sqlalchemy.engine import CursorResult, Result
from sqlalchemy.ext.asyncio import AsyncSession

from wiredex.firmware.application.ports import VersionSummary
from wiredex.firmware.domain.firmware import Firmware
from wiredex.firmware.domain.source import SourceFile, SourceFiles
from wiredex.firmware.domain.values import (
    FirmwareId,
    FirmwareName,
    RevisionId,
    SourceFileId,
    VersionId,
    WorkspaceId,
)
from wiredex.firmware.domain.version import FirmwareVersion, FirmwareVersions
from wiredex.firmware.infrastructure.orm import (
    firmware_revisions,
    firmware_table,
    firmware_versions,
    folded_name,
    source_files,
)

# Escaped rather than passed through: someone searching for "100%" means the characters, not
# every firmware in the workspace (requirement 2.3). The backslash goes first, or it would
# double the ones the wildcards just added.
_LIKE_WILDCARDS = str.maketrans({"\\": "\\\\", "%": "\\%", "_": "\\_"})
_LIKE_ESCAPE = "\\"

# Reload the rows a query finds even when the session already holds them, instead of keeping
# the attributes it read earlier in the transaction.
_FRESH: dict[str, Any] = {"populate_existing": True}


class SqlFirmwares:
    def __init__(self, session: AsyncSession, workspace_id: WorkspaceId) -> None:
        self._session = session
        self._workspace_id = workspace_id

    async def add(self, firmware: Firmware) -> None:
        """Written at once, so a link inserted with Core in the same transaction finds the row
        its key points at (requirement 3.3). Nothing commits; the unit of work still does."""
        self._session.add(firmware)
        await self._session.flush()

    async def get(self, firmware_id: FirmwareId) -> Firmware | None:
        # Not session.get(), which reads by primary key alone: another workspace's id has to
        # come back as nothing found, never as a row.
        found = await self._session.execute(self._mine().where(firmware_table.c.id == firmware_id))
        return found.scalar_one_or_none()

    async def locked(self, firmware_id: FirmwareId) -> Firmware | None:
        """The firmware, its row locked until the transaction ends (decision 8).

        A second write to the same firmware waits here until the first commits, and then reads
        the firmware, and whatever it reads of it next, as that one left them.
        """
        found = await self._session.execute(
            self._mine()
            .where(firmware_table.c.id == firmware_id)
            .with_for_update()
            .execution_options(**_FRESH)
        )
        return found.scalar_one_or_none()

    async def named(self, name: FirmwareName) -> Firmware | None:
        """Compared on `lower(name)`, the unique index's own expression, so the check uses the
        index and agrees with what it enforces (requirement 1.3)."""
        found = await self._session.execute(self._mine().where(folded_name == name.fold()))
        return found.scalar_one_or_none()

    async def matching(self, text: str) -> list[Firmware]:
        """An escaped `ILIKE` over the name and the target (requirement 2.3), last change first
        (2.2): the id breaks a tie on the clock, newer first, as UUIDv7 is time-ordered."""
        statement = self._mine()
        if text:
            pattern = _containing(text)
            statement = statement.where(
                or_(
                    firmware_table.c.name.ilike(pattern, escape=_LIKE_ESCAPE),
                    firmware_table.c.target.ilike(pattern, escape=_LIKE_ESCAPE),
                )
            )
        found = await self._session.execute(
            statement.order_by(firmware_table.c.updated_at.desc(), firmware_table.c.id.desc())
        )
        return list(found.scalars())

    async def running_on(self, revision_id: RevisionId) -> list[Firmware]:
        """The firmware linked to the revision, in one join (requirement 3.4).

        Sorted here rather than by the database, whose collation may order names differently
        from the code-point order `FirmwareName.fold` gives. Folded names are unique, so the
        order is total.
        """
        found = await self._session.execute(
            self._mine()
            .join(
                firmware_revisions,
                and_(
                    firmware_revisions.c.workspace_id == firmware_table.c.workspace_id,
                    firmware_revisions.c.firmware_id == firmware_table.c.id,
                ),
            )
            .where(firmware_revisions.c.revision_id == revision_id)
        )
        return sorted(found.scalars(), key=lambda firmware: firmware.name.fold())

    async def remove(self, firmware: Firmware) -> None:
        # Its links and versions go with it, and the versions' files with them, by the
        # composite keys' ON DELETE CASCADE (requirement 1.9).
        await self._session.delete(firmware)

    def _mine(self) -> Select[tuple[Firmware]]:
        return select(Firmware).where(firmware_table.c.workspace_id == self._workspace_id)


class SqlVersions:
    def __init__(self, session: AsyncSession, workspace_id: WorkspaceId) -> None:
        self._session = session
        self._workspace_id = workspace_id

    async def add(self, version: FirmwareVersion) -> None:
        """Written at once, so its files, inserted with Core in the same transaction, find the
        row their key points at. Nothing commits; the unit of work still does."""
        self._session.add(version)
        await self._session.flush()

    async def get(self, version_id: VersionId) -> FirmwareVersion | None:
        """Fresh: `lock_version` reads it after its firmware's lock, and a copy the session
        already held is refreshed with the row as the lock left it instead of handed back stale
        (decision 8)."""
        found = await self._session.execute(
            self._mine().where(firmware_versions.c.id == version_id).execution_options(**_FRESH)
        )
        return found.scalar_one_or_none()

    async def firmware_of(self, version_id: VersionId) -> FirmwareId | None:
        """One column, so nothing enters the session before the firmware is locked."""
        found = await self._session.execute(
            select(firmware_versions.c.firmware_id).where(
                firmware_versions.c.workspace_id == self._workspace_id,
                firmware_versions.c.id == version_id,
            )
        )
        firmware_id = found.scalar_one_or_none()
        return None if firmware_id is None else FirmwareId(firmware_id)

    async def of_firmware(self, firmware_id: FirmwareId) -> FirmwareVersions:
        """One read, fresh: called under the firmware's lock (decision 8). `FirmwareVersions`
        orders them by precedence, which the stored text can't: as text, `1.10.0` comes before
        `1.2.0`."""
        found = await self._session.execute(
            self._mine()
            .where(firmware_versions.c.firmware_id == firmware_id)
            .execution_options(**_FRESH)
        )
        return FirmwareVersions.of(found.scalars())

    async def summaries(
        self, firmware_ids: Collection[FirmwareId]
    ) -> Mapping[FirmwareId, tuple[VersionSummary, ...]]:
        """Every listed firmware's versions with their file counts and sizes, in one aggregate
        whatever their numbers (decision 12): the stored sizes are summed, so no text is read
        (decision 9). Grouped by the version's key, which Postgres lets the version's other
        columns ride on. A firmware with no version is absent."""
        if not firmware_ids:
            return {}
        rows = await self._session.execute(
            select(
                FirmwareVersion,
                func.count(source_files.c.id),
                func.coalesce(func.sum(source_files.c.size), 0),
            )
            .outerjoin(
                source_files,
                and_(
                    source_files.c.workspace_id == firmware_versions.c.workspace_id,
                    source_files.c.version_id == firmware_versions.c.id,
                ),
            )
            .where(
                firmware_versions.c.workspace_id == self._workspace_id,
                firmware_versions.c.firmware_id.in_(list(firmware_ids)),
            )
            .group_by(firmware_versions.c.id)
        )
        held: dict[VersionId, tuple[int, int]] = {}
        grouped: dict[FirmwareId, list[FirmwareVersion]] = {}
        for version, files, size in rows.tuples():
            held[version.id] = (int(files), int(size))
            grouped.setdefault(version.firmware_id, []).append(version)
        return {
            firmware_id: tuple(
                VersionSummary(version, *held[version.id])
                for version in FirmwareVersions.of(versions).items
            )
            for firmware_id, versions in grouped.items()
        }

    async def remove(self, version: FirmwareVersion) -> None:
        # Its files go with it, by the composite key's ON DELETE CASCADE, and a version started
        # from it keeps going, its `based_on` cleared by ON DELETE SET NULL (requirement 8.2).
        await self._session.delete(version)

    def _mine(self) -> Select[tuple[FirmwareVersion]]:
        return select(FirmwareVersion).where(firmware_versions.c.workspace_id == self._workspace_id)


class SqlSources:
    """A version's source files (decision 9), each row carrying its text's size."""

    def __init__(self, session: AsyncSession, workspace_id: WorkspaceId) -> None:
        self._session = session
        self._workspace_id = workspace_id

    async def of_version(self, version_id: VersionId) -> SourceFiles:
        """One read whatever their number; `SourceFiles` lists them `.ino` first, then by folded
        path (requirement 7.10)."""
        rows = await self._session.execute(
            select(source_files.c.id, source_files.c.path, source_files.c.content).where(
                self._files_of(version_id)
            )
        )
        return SourceFiles.of(
            SourceFile(SourceFileId(file_id), path, text) for file_id, path, text in rows.tuples()
        )

    async def add_all(self, version_id: VersionId, files: Sequence[SourceFile]) -> None:
        """One statement whatever their number, a batch or a base's copy. The version was
        flushed when it was added, so its key finds the row."""
        if not files:
            return
        await self._session.execute(
            insert(source_files), [self._row_of(version_id, file) for file in files]
        )

    async def update(self, version_id: VersionId, before: SourceFile, after: SourceFile) -> None:
        """The path, the text and its size, under the id the file keeps (decision 10)."""
        await self._session.execute(
            update_rows(source_files)
            .where(self._files_of(version_id), source_files.c.id == before.id)
            .values(path=after.path, content=after.text, size=after.text.size)
        )

    async def remove(self, version_id: VersionId, file: SourceFile) -> None:
        await self._session.execute(
            delete(source_files).where(self._files_of(version_id), source_files.c.id == file.id)
        )

    def _row_of(self, version_id: VersionId, file: SourceFile) -> dict[str, Any]:
        return {
            "id": file.id,
            "workspace_id": self._workspace_id,
            "version_id": version_id,
            "path": file.path,
            "content": file.text,
            "size": file.text.size,
        }

    def _files_of(self, version_id: VersionId) -> ColumnElement[bool]:
        # `uq_source_files_path` answers it, leading with the workspace and the version.
        return and_(
            source_files.c.workspace_id == self._workspace_id,
            source_files.c.version_id == version_id,
        )


class SqlRevisionLinks:
    """The revisions each firmware runs on (decision 2), each named by a bare id."""

    def __init__(self, session: AsyncSession, workspace_id: WorkspaceId) -> None:
        self._session = session
        self._workspace_id = workspace_id

    async def of_firmware(self, firmware_id: FirmwareId) -> tuple[RevisionId, ...]:
        """In the order they were linked (requirement 3.5), two linked at one instant by the
        revision's id."""
        rows = await self._session.execute(
            select(firmware_revisions.c.revision_id)
            .where(self._links_of(firmware_id))
            .order_by(firmware_revisions.c.created_at, firmware_revisions.c.revision_id)
        )
        return tuple(RevisionId(revision_id) for revision_id in rows.scalars())

    async def add(self, firmware_id: FirmwareId, revision_id: RevisionId, at: datetime) -> bool:
        """One insert that leaves a link already there as it was, its date included, and says
        whether it wrote a row (requirement 3.1)."""
        added = await self._session.execute(
            upsert(firmware_revisions)
            .values(
                workspace_id=self._workspace_id,
                firmware_id=firmware_id,
                revision_id=revision_id,
                created_at=at,
            )
            .on_conflict_do_nothing()
        )
        return _changed(added)

    async def remove(self, firmware_id: FirmwareId, revision_id: RevisionId) -> bool:
        removed = await self._session.execute(
            delete(firmware_revisions).where(
                self._links_of(firmware_id), firmware_revisions.c.revision_id == revision_id
            )
        )
        return _changed(removed)

    async def copy(self, source: RevisionId, target: RevisionId, at: datetime) -> None:
        """Two statements whatever the number of links (decision 4): the source's links given
        to the target, dated `at`, and those firmware's last change moved to `at`."""
        running = firmware_revisions.c.revision_id == source
        mine = firmware_revisions.c.workspace_id == self._workspace_id
        await self._session.execute(
            upsert(firmware_revisions)
            .from_select(
                ["workspace_id", "firmware_id", "revision_id", "created_at"],
                select(
                    firmware_revisions.c.workspace_id,
                    firmware_revisions.c.firmware_id,
                    literal(target, Uuid()),
                    literal(at, DateTime(timezone=True)),
                ).where(mine, running),
            )
            .on_conflict_do_nothing()
        )
        await self._session.execute(
            update_rows(firmware_table)
            .where(
                firmware_table.c.workspace_id == self._workspace_id,
                firmware_table.c.id.in_(
                    select(firmware_revisions.c.firmware_id).where(mine, running)
                ),
            )
            .values(updated_at=at)
        )

    def _links_of(self, firmware_id: FirmwareId) -> ColumnElement[bool]:
        return and_(
            firmware_revisions.c.workspace_id == self._workspace_id,
            firmware_revisions.c.firmware_id == firmware_id,
        )


def _changed(result: Result[Any]) -> bool:
    """Whether a Core write touched a row: a link already there, or none to remove, is none."""
    return cast("CursorResult[Any]", result).rowcount > 0


def _containing(text: str) -> str:
    return f"%{text.translate(_LIKE_WILDCARDS)}%"
