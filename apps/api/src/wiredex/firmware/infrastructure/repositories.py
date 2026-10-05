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

Links, source files and flashes are written with Core, as projects' BOM lines and nets are: none
has an identity worth an ORM object, and each read or write is one statement whatever the number
of rows.
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
from sqlalchemy.engine import CursorResult, Result, RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from wiredex.firmware.application.ports import FlashEntry, VersionSummary
from wiredex.firmware.domain.firmware import Firmware
from wiredex.firmware.domain.flash import Flash
from wiredex.firmware.domain.source import SourceFile, SourceFiles
from wiredex.firmware.domain.values import (
    FirmwareId,
    FirmwareName,
    FlashId,
    RevisionId,
    SourceFileId,
    UnitId,
    VersionId,
    WorkspaceId,
)
from wiredex.firmware.domain.version import FirmwareVersion, FirmwareVersions
from wiredex.firmware.infrastructure.orm import (
    firmware_revisions,
    firmware_table,
    firmware_versions,
    flashes,
    folded_name,
    source_files,
)
from wiredex.shared_kernel.domain.trash import TrashedSlice
from wiredex.shared_kernel.infrastructure.trash import in_the_trash, live, sliced, trash_newest

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
        index and agrees with what it enforces (requirement 1.3). A firmware in the trash keeps
        its name, as the index does (16-soft-delete-and-trash, decision 5)."""
        found = await self._session.execute(self._any().where(folded_name == name.fold()))
        return found.scalar_one_or_none()

    async def find(self, text: str, limit: int) -> list[Firmware]:
        pattern = _containing(text)
        found = await self._session.execute(
            self._mine()
            .where(
                or_(
                    firmware_table.c.name.ilike(pattern, escape=_LIKE_ESCAPE),
                    firmware_table.c.target.ilike(pattern, escape=_LIKE_ESCAPE),
                )
            )
            .order_by(*_starting_first(firmware_table.c.name, text), firmware_table.c.id)
            .limit(limit)
        )
        return list(found.scalars())

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

    async def trashed(self, count: int, text: str | None) -> TrashedSlice[Firmware]:
        """The newest of the trash and their total in one statement, over `ix_firmware_trashed`
        (16's decision 9)."""
        statement = self._any()
        if text is not None:
            pattern = _containing(text)
            statement = statement.where(
                or_(
                    firmware_table.c.name.ilike(pattern, escape=_LIKE_ESCAPE),
                    firmware_table.c.target.ilike(pattern, escape=_LIKE_ESCAPE),
                )
            )
        found = await self._session.execute(trash_newest(statement, firmware_table, count))
        return sliced(found.tuples())

    async def in_trash(self, firmware_id: FirmwareId) -> Firmware | None:
        """Locked and fresh, so a restore and a delete for good of one firmware take turns, and
        the second finds nothing (16's decision 10)."""
        found = await self._session.execute(
            self._any()
            .where(firmware_table.c.id == firmware_id, in_the_trash(firmware_table))
            .with_for_update()
            .execution_options(**_FRESH)
        )
        return found.scalar_one_or_none()

    async def empty_trash(self) -> int:
        """One `DELETE`; each row it takes is locked and checked again, so a restore racing it
        either wins or finds nothing. Versions, files and links go by the keys' cascades; no
        flash names a version of a firmware in the trash, since moving it there refuses one."""
        result = await self._session.execute(
            delete(firmware_table).where(
                firmware_table.c.workspace_id == self._workspace_id, in_the_trash(firmware_table)
            )
        )
        return cast("CursorResult[Any]", result).rowcount

    def _mine(self) -> Select[tuple[Firmware]]:
        """The workspace's live firmware: every read but the trash's own and the name check goes
        through here, so a firmware in the trash is absent everywhere (16's decision 2). `locked`
        locks through it, so a lock taken after a move to the trash finds nothing (decision 3).
        """
        return self._any().where(live(firmware_table))

    def _any(self) -> Select[tuple[Firmware]]:
        """The workspace's firmware, in the trash or not."""
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
                _of_a_live_firmware(),
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
        """The workspace's versions of live firmware: a version is in the trash when its firmware
        is (16-soft-delete-and-trash, decision 2)."""
        return select(FirmwareVersion).where(
            firmware_versions.c.workspace_id == self._workspace_id, _of_a_live_firmware()
        )


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
        to the target, dated `at`, and those firmware's last change moved to `at`. A firmware in
        the trash is absent, so its link stays behind (16's requirement 2.4)."""
        running = and_(firmware_revisions.c.revision_id == source, _linking_live_firmware())
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


def _of_a_live_firmware() -> ColumnElement[bool]:
    """The version's firmware isn't in the trash: correlated to the version row, over the
    firmware's primary key."""
    return (
        select(literal(1))
        .where(
            firmware_table.c.workspace_id == firmware_versions.c.workspace_id,
            firmware_table.c.id == firmware_versions.c.firmware_id,
            live(firmware_table),
        )
        .correlate(firmware_versions)
        .exists()
    )


def _linking_live_firmware() -> ColumnElement[bool]:
    """The link's firmware isn't in the trash."""
    return (
        select(literal(1))
        .where(
            firmware_table.c.workspace_id == firmware_revisions.c.workspace_id,
            firmware_table.c.id == firmware_revisions.c.firmware_id,
            live(firmware_table),
        )
        .correlate(firmware_revisions)
        .exists()
    )


# A flash's version, by the pair its key holds.
_VERSION_OF_FLASH = and_(
    firmware_versions.c.workspace_id == flashes.c.workspace_id,
    firmware_versions.c.id == flashes.c.version_id,
)
# `Flash.order` reversed, which `ix_flashes_unit` holds after the workspace and the unit.
_NEWEST_FIRST = (flashes.c.flashed_at.desc(), flashes.c.created_at.desc(), flashes.c.id.desc())


class SqlFlashes:
    """The flash log (15-flash-log decision 1), written with Core as the source files are: a
    flash is frozen and never edited (decision 5), with no identity worth an ORM object.

    An entry is read in one join to its version and its firmware, on the pairs the keys use, so
    each list is one statement whatever the numbers of flashes, units and versions (requirement
    9.3), and each comes in a total order.
    """

    def __init__(self, session: AsyncSession, workspace_id: WorkspaceId) -> None:
        self._session = session
        self._workspace_id = workspace_id

    async def add(self, flash: Flash) -> None:
        """Under the flash's own workspace, its version's: the key refuses it unless the version
        is that workspace's (requirement 6.3), and the policy unless the workspace is the
        transaction's."""
        await self._session.execute(insert(flashes).values(_flash_row(flash)))

    async def get(self, flash_id: FlashId) -> Flash | None:
        found = await self._session.execute(
            select(*flashes.c).where(self._mine(), flashes.c.id == flash_id)
        )
        row = found.mappings().one_or_none()
        return None if row is None else _flash_of(row)

    async def remove(self, flash: Flash) -> None:
        await self._session.execute(delete(flashes).where(self._mine(), flashes.c.id == flash.id))

    async def of_unit(self, unit_id: UnitId) -> list[FlashEntry]:
        """Newest first, `ix_flashes_unit`'s own order (decision 4)."""
        return await self._read(
            self._entries().where(flashes.c.unit_id == unit_id).order_by(*_NEWEST_FIRST)
        )

    async def current_on(self, firmware_id: FirmwareId) -> list[FlashEntry]:
        """Each unit's newest flash, kept when its version is the firmware's (decision 11), by
        the unit's recorded code, then its id.

        One statement. `DISTINCT ON (unit_id)` keeps each unit's first row in
        `ix_flashes_unit`'s order, among the units any flash of the firmware names, and the
        outer query keeps those whose version is the firmware's. Filtering on the firmware
        before the `DISTINCT ON` would answer each unit's newest flash of this firmware, which
        isn't what the unit runs once another firmware went on after it.
        """
        named = (
            select(flashes.c.unit_id)
            .join(firmware_versions, _VERSION_OF_FLASH)
            .where(self._mine(), firmware_versions.c.firmware_id == firmware_id)
        )
        newest = (
            select(
                *flashes.c,
                firmware_versions.c.firmware_id,
                firmware_versions.c.version.label("number"),
            )
            .join(firmware_versions, _VERSION_OF_FLASH)
            .where(self._mine(), flashes.c.unit_id.in_(named))
            .distinct(flashes.c.unit_id)
            .order_by(flashes.c.unit_id, *_NEWEST_FIRST)
            .subquery("newest")
        )
        return await self._read(
            select(
                *(newest.c[column.name] for column in flashes.c),
                newest.c.firmware_id,
                firmware_table.c.name.label("firmware_name"),
                newest.c.number,
            )
            .select_from(newest)
            .join(
                firmware_table,
                and_(
                    firmware_table.c.workspace_id == newest.c.workspace_id,
                    firmware_table.c.id == newest.c.firmware_id,
                ),
            )
            .where(newest.c.firmware_id == firmware_id)
            .order_by(newest.c.unit_code, newest.c.unit_id)
        )

    async def of_version(self, version_id: VersionId) -> list[FlashEntry]:
        """What keeps the version (decision 6): by the unit's recorded code, so a board's
        entries stand together, then newest first. `ix_flashes_version` finds them."""
        return await self._read(
            self._entries()
            .where(flashes.c.version_id == version_id)
            .order_by(flashes.c.unit_code, *_NEWEST_FIRST)
        )

    async def of_firmware(self, firmware_id: FirmwareId) -> list[FlashEntry]:
        """What keeps the firmware: the flashes of any of its versions, in `of_version`'s
        order."""
        return await self._read(
            self._entries()
            .where(firmware_versions.c.firmware_id == firmware_id)
            .order_by(flashes.c.unit_code, *_NEWEST_FIRST)
        )

    def _entries(self) -> Select[Any]:
        """Every flash of the workspace with its version's firmware and number, in one join."""
        return (
            select(
                *flashes.c,
                firmware_versions.c.firmware_id,
                firmware_table.c.name.label("firmware_name"),
                firmware_versions.c.version.label("number"),
            )
            .select_from(flashes)
            .join(firmware_versions, _VERSION_OF_FLASH)
            .join(
                firmware_table,
                and_(
                    firmware_table.c.workspace_id == firmware_versions.c.workspace_id,
                    firmware_table.c.id == firmware_versions.c.firmware_id,
                ),
            )
            .where(self._mine())
        )

    async def _read(self, statement: Select[Any]) -> list[FlashEntry]:
        rows = await self._session.execute(statement)
        return [
            FlashEntry(_flash_of(row), row["firmware_id"], row["firmware_name"], row["number"])
            for row in rows.mappings()
        ]

    def _mine(self) -> ColumnElement[bool]:
        return flashes.c.workspace_id == self._workspace_id


def _flash_row(flash: Flash) -> dict[str, Any]:
    return {
        "id": flash.id,
        "workspace_id": flash.workspace_id,
        "unit_id": flash.unit_id,
        "unit_code": flash.unit_code,
        "version_id": flash.version_id,
        "revision_id": flash.revision_id,
        "flashed_at": flash.flashed_at,
        "notes": flash.notes,
        "created_at": flash.created_at,
    }


def _flash_of(row: RowMapping) -> Flash:
    """A flash as its row holds it; the column types rebuild the code and the notes."""
    return Flash(
        id=row["id"],
        workspace_id=row["workspace_id"],
        unit_id=row["unit_id"],
        unit_code=row["unit_code"],
        version_id=row["version_id"],
        revision_id=row["revision_id"],
        flashed_at=row["flashed_at"],
        notes=row["notes"],
        created_at=row["created_at"],
    )


def _changed(result: Result[Any]) -> bool:
    """Whether a Core write touched a row: a link already there, or none to remove, is none."""
    return cast("CursorResult[Any]", result).rowcount > 0


def _containing(text: str) -> str:
    return f"%{text.translate(_LIKE_WILDCARDS)}%"


def _starting_first(title: ColumnElement[Any], text: str) -> tuple[ColumnElement[Any], ...]:
    """A find's order (19-command-palette, decision 2): the titles starting with the text
    first, then the rest, each by the title folded. `COLLATE "C"` orders by code point, as
    Python's sort does, whatever collation the database was created with."""
    starting = f"{text.translate(_LIKE_WILDCARDS)}%"
    return (
        title.ilike(starting, escape=_LIKE_ESCAPE).desc(),
        func.lower(title).collate("C"),
    )
