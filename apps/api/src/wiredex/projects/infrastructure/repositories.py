"""Projects in PostgreSQL: one repository per port, each bound to one workspace.

Every statement filters `workspace_id` itself, the first of ADR 0007's two gates, even though
the policies on these tables already hide another workspace's rows: the filter is what makes a
query's scope readable, and what still holds if a connection ever runs without the setting the
policies read.

The project row is also the lock that makes changes to one project's revisions, and to their
BOMs, take turns (08's decision 15, 09's decision 12). `locked`, `of_project` and `get`
refresh what the session already holds, because a use case may read a revision before it waits
for that lock, and what it read may have changed by the time the lock is granted.

A BOM is written with Core, as a pinout is: its lines and designators are values written back
whole, and each read or write is one statement per table whatever the number of rows.
"""

from collections.abc import Iterable, Mapping, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, Row, Select, String, and_, delete, func, insert, select
from sqlalchemy import update as update_rows
from sqlalchemy.ext.asyncio import AsyncSession

from wiredex.projects.application.ports import BomUse, BomUses, TagCount
from wiredex.projects.domain.bom import BillOfMaterials, BomLine, LineContent
from wiredex.projects.domain.designators import Designator, Designators
from wiredex.projects.domain.filter import ProjectFilter
from wiredex.projects.domain.project import Project
from wiredex.projects.domain.project_revisions import ProjectRevisions
from wiredex.projects.domain.revision import Revision
from wiredex.projects.domain.values import (
    MAX_TAG_LENGTH,
    BomLineId,
    PartId,
    ProjectId,
    ProjectName,
    RevisionId,
    Tag,
    WorkspaceId,
)
from wiredex.projects.infrastructure.orm import (
    bom_designators,
    bom_lines,
    folded_name,
    projects,
    revisions,
)

# Escaped rather than passed through: someone searching for "100%" means the characters, not
# every project in the workspace (requirement 3.3). The backslash goes first, or it would
# double the ones the wildcards just added.
_LIKE_WILDCARDS = str.maketrans({"\\": "\\\\", "%": "\\%", "_": "\\_"})
_LIKE_ESCAPE = "\\"

# Reload the rows a query finds even when the session already holds them, instead of keeping
# the attributes it read earlier in the transaction.
_FRESH: dict[str, Any] = {"populate_existing": True}


class SqlProjects:
    def __init__(self, session: AsyncSession, workspace_id: WorkspaceId) -> None:
        self._session = session
        self._workspace_id = workspace_id

    async def add(self, project: Project) -> None:
        self._session.add(project)

    async def get(self, project_id: ProjectId) -> Project | None:
        # Not session.get(), which reads by primary key alone: another workspace's id has to
        # come back as nothing found, never as a row.
        found = await self._session.execute(self._mine().where(projects.c.id == project_id))
        return found.scalar_one_or_none()

    async def locked(self, project_id: ProjectId) -> Project | None:
        """The project, its row locked until the transaction ends (decision 15).

        A second change to the same project's revisions waits here until the first commits,
        and then reads the siblings as that one left them.
        """
        found = await self._session.execute(
            self._mine()
            .where(projects.c.id == project_id)
            .with_for_update()
            .execution_options(**_FRESH)
        )
        return found.scalar_one_or_none()

    async def named(self, name: ProjectName) -> Project | None:
        """Compared on `lower(name)`, the unique index's own expression, so the check uses the
        index and agrees with what it enforces (decision 9)."""
        found = await self._session.execute(self._mine().where(folded_name == name.fold()))
        return found.scalar_one_or_none()

    async def matching(self, wanted: ProjectFilter) -> list[Project]:
        """`ProjectFilter.matches` in SQL: an `ILIKE` over the name, and `tags @> :wanted`,
        which the GIN index answers (requirements 3.3, 3.4)."""
        statement = self._mine()
        if wanted.text is not None:
            statement = statement.where(
                projects.c.name.ilike(_containing(wanted.text), escape=_LIKE_ESCAPE)
            )
        if wanted.tags.values:
            statement = statement.where(projects.c.tags.contains(wanted.tags))
        found = await self._session.execute(statement)
        return list(found.scalars())

    async def tag_counts(self) -> list[TagCount]:
        """Each tag once with the number of projects carrying it (requirement 2.6).

        A project holds each tag once, so counting the unnested rows counts projects. Sorted
        here rather than by the database, whose collation may order text differently from the
        code-point order `Tags` keeps a project's own tags in.
        """
        carried = (
            select(func.unnest(projects.c.tags, type_=String(MAX_TAG_LENGTH)).label("tag"))
            .where(projects.c.workspace_id == self._workspace_id)
            .subquery()
        )
        rows = await self._session.execute(
            select(carried.c.tag, func.count()).group_by(carried.c.tag)
        )
        counts = [TagCount(Tag(text), int(total)) for text, total in rows.tuples()]
        return sorted(counts, key=lambda count: count.tag.value)

    async def remove(self, project: Project) -> None:
        # The revisions go with it, by the composite key's ON DELETE CASCADE.
        await self._session.delete(project)

    def _mine(self) -> Select[tuple[Project]]:
        return select(Project).where(projects.c.workspace_id == self._workspace_id)


class SqlRevisions:
    def __init__(self, session: AsyncSession, workspace_id: WorkspaceId) -> None:
        self._session = session
        self._workspace_id = workspace_id

    async def add(self, revision: Revision) -> None:
        """Written at once, so content a fork copies with Core finds the row it points at.

        The mapping declares no relationship, so a flush can't know a project added in this
        same transaction must be inserted before its revision: the first flush settles it, the
        second writes the revision. Neither commits; the unit of work still does.
        """
        await self._session.flush()
        self._session.add(revision)
        await self._session.flush()

    async def get(self, revision_id: RevisionId) -> Revision | None:
        """Fresh: `lock_revision` reads it after the project's lock, and a copy the session
        already held is refreshed with the row as the lock left it instead of handed back
        stale (09's decision 12)."""
        found = await self._session.execute(
            self._mine().where(revisions.c.id == revision_id).execution_options(**_FRESH)
        )
        return found.scalar_one_or_none()

    async def project_of(self, revision_id: RevisionId) -> ProjectId | None:
        """One column, so nothing enters the session before the project is locked."""
        found = await self._session.execute(
            select(revisions.c.project_id).where(
                revisions.c.workspace_id == self._workspace_id, revisions.c.id == revision_id
            )
        )
        project_id = found.scalar_one_or_none()
        return None if project_id is None else ProjectId(project_id)

    async def of_project(self, project_id: ProjectId) -> ProjectRevisions:
        """One read, oldest first, fresh: called under the project's lock (decision 15)."""
        found = await self._session.execute(
            self._ordered().where(revisions.c.project_id == project_id).execution_options(**_FRESH)
        )
        return ProjectRevisions(tuple(found.scalars()))

    async def of_projects(
        self, project_ids: Sequence[ProjectId]
    ) -> Mapping[ProjectId, ProjectRevisions]:
        """Every listed project's revisions in one read, whatever their number (11.3)."""
        if not project_ids:
            return {}
        found = await self._session.execute(
            self._ordered().where(revisions.c.project_id.in_(project_ids))
        )
        grouped: dict[ProjectId, list[Revision]] = {}
        for revision in found.scalars():
            grouped.setdefault(revision.project_id, []).append(revision)
        return {project_id: ProjectRevisions(tuple(items)) for project_id, items in grouped.items()}

    async def remove(self, revision: Revision) -> None:
        # A revision forked from it keeps going: `forked_from` is cleared by ON DELETE SET NULL.
        await self._session.delete(revision)

    def _mine(self) -> Select[tuple[Revision]]:
        return select(Revision).where(revisions.c.workspace_id == self._workspace_id)

    def _ordered(self) -> Select[tuple[Revision]]:
        # The id breaks a tie on the clock, as `ProjectRevisions` does: UUIDv7 is time-ordered.
        return self._mine().order_by(revisions.c.created_at, revisions.c.id)


class SqlBomLines:
    """A revision's BOM lines and their designators (09's decisions 8 and 9)."""

    def __init__(self, session: AsyncSession, workspace_id: WorkspaceId) -> None:
        self._session = session
        self._workspace_id = workspace_id

    async def of_revision(self, revision_id: RevisionId) -> BillOfMaterials:
        """Two reads whatever the size (12.3): the lines oldest first, then every designator
        of the revision, grouped per line. The id breaks a tie on the clock, as UUIDv7 is
        time-ordered, so a fork's copies, which share its date, keep the source's order."""
        lines = await self._session.execute(
            select(bom_lines)
            .where(self._lines_of(revision_id))
            .order_by(bom_lines.c.created_at, bom_lines.c.id)
        )
        held = await self._session.execute(
            select(bom_designators.c.line_id, bom_designators.c.designator).where(
                bom_designators.c.workspace_id == self._workspace_id,
                bom_designators.c.revision_id == revision_id,
            )
        )
        by_line: dict[UUID, list[Designator]] = {}
        for line_id, designator in held.tuples():
            by_line.setdefault(line_id, []).append(designator)
        return BillOfMaterials(
            revision_id, tuple(_line_of(row, by_line.get(row.id, ())) for row in lines)
        )

    async def add(self, line: BomLine) -> None:
        await self.add_all((line,))

    async def add_all(self, lines: Sequence[BomLine]) -> None:
        """One statement for the lines and one for their designators, whatever their number.

        The flush first, as `SqlPinouts.replace` does: a Core statement doesn't autoflush, so
        a fork's revision, added in this same unit of work, would still be pending and the
        lines' composite key would refuse them.
        """
        await self._session.flush()
        if not lines:
            return
        await self._session.execute(insert(bom_lines), [self._row_of(line) for line in lines])
        await self._insert_designators(
            (line, designator) for line in lines for designator in line.content.designators
        )

    async def update(self, before: BomLine, after: BomLine) -> None:
        """The part, quantity and notes, then only the designators that differ: an edit from
        `R1–R3` to `R2–R4` deletes `R1`, inserts `R4` and keeps the rows of `R2` and `R3`,
        so whatever 11 hangs off them survives (decision 8)."""
        content = after.content
        await self._session.execute(
            update_rows(bom_lines)
            .where(bom_lines.c.workspace_id == self._workspace_id, bom_lines.c.id == after.id)
            .values(part_id=content.part_id, quantity=content.quantity, notes=content.notes)
        )
        kept = set(before.content.designators)
        wanted = set(content.designators)
        if gone := kept - wanted:
            await self._session.execute(
                delete(bom_designators).where(
                    self._designators_of(after), bom_designators.c.designator.in_(sorted(gone))
                )
            )
        await self._insert_designators((after, designator) for designator in sorted(wanted - kept))

    async def remove(self, line: BomLine) -> None:
        # Its designators go with it, by the composite key's ON DELETE CASCADE.
        await self._session.execute(
            delete(bom_lines).where(
                bom_lines.c.workspace_id == self._workspace_id, bom_lines.c.id == line.id
            )
        )

    async def uses_of(self, part_id: PartId, limit: int) -> BomUses:
        """The revisions naming the part, one row each however many of its lines do, by the
        project's name folded and then the oldest revision first; the count in a second read."""
        naming = select(bom_lines.c.revision_id).where(self._naming(part_id))
        rows = await self._session.execute(
            select(projects.c.id, projects.c.name, revisions.c.id, revisions.c.label)
            .join(
                projects,
                and_(
                    projects.c.workspace_id == revisions.c.workspace_id,
                    projects.c.id == revisions.c.project_id,
                ),
            )
            .where(revisions.c.workspace_id == self._workspace_id, revisions.c.id.in_(naming))
            .order_by(func.lower(projects.c.name), revisions.c.created_at, revisions.c.id)
            .limit(limit)
        )
        uses = tuple(
            BomUse(ProjectId(project_id), name, RevisionId(revision_id), label)
            for project_id, name, revision_id, label in rows.tuples()
        )
        total = await self._session.scalar(
            select(func.count(func.distinct(bom_lines.c.revision_id))).where(self._naming(part_id))
        )
        return BomUses(uses, total or 0)

    async def _insert_designators(self, held: Iterable[tuple[BomLine, Designator]]) -> None:
        rows = [
            {
                "workspace_id": line.workspace_id,
                "revision_id": line.revision_id,
                "line_id": line.id,
                "designator": designator,
            }
            for line, designator in held
        ]
        if rows:
            await self._session.execute(insert(bom_designators), rows)

    def _row_of(self, line: BomLine) -> dict[str, Any]:
        content = line.content
        return {
            "id": line.id,
            "workspace_id": line.workspace_id,
            "revision_id": line.revision_id,
            "part_id": content.part_id,
            "quantity": content.quantity,
            "notes": content.notes,
            "created_at": line.created_at,
        }

    def _lines_of(self, revision_id: RevisionId) -> ColumnElement[bool]:
        return and_(
            bom_lines.c.workspace_id == self._workspace_id, bom_lines.c.revision_id == revision_id
        )

    def _designators_of(self, line: BomLine) -> ColumnElement[bool]:
        """One line's designators, named by the whole key their foreign key uses."""
        return and_(
            bom_designators.c.workspace_id == self._workspace_id,
            bom_designators.c.revision_id == line.revision_id,
            bom_designators.c.line_id == line.id,
        )

    def _naming(self, part_id: PartId) -> ColumnElement[bool]:
        # `ix_bom_lines_part` answers it.
        return and_(bom_lines.c.workspace_id == self._workspace_id, bom_lines.c.part_id == part_id)


def _line_of(row: Row[Any], designators: Iterable[Designator]) -> BomLine:
    content = LineContent(PartId(row.part_id), Designators.of(designators), row.quantity, row.notes)
    return BomLine(
        BomLineId(row.id),
        WorkspaceId(row.workspace_id),
        RevisionId(row.revision_id),
        content,
        row.created_at,
    )


def _containing(text: str) -> str:
    return f"%{text.translate(_LIKE_WILDCARDS)}%"
