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
from typing import Any, cast
from uuid import UUID

from sqlalchemy import (
    ColumnElement,
    Row,
    Select,
    String,
    and_,
    delete,
    func,
    insert,
    literal,
    select,
)
from sqlalchemy import update as update_rows
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from wiredex.projects.application.ports import BomUse, BomUses, RevisionRef, TagCount
from wiredex.projects.domain.bom import BillOfMaterials, BomLine, LineContent
from wiredex.projects.domain.designators import Designator, Designators
from wiredex.projects.domain.filter import ProjectFilter
from wiredex.projects.domain.netlist import Net, NetContent, Netlist, NetPins, PinReference
from wiredex.projects.domain.pin_usage import PinUse
from wiredex.projects.domain.project import Project
from wiredex.projects.domain.project_revisions import ProjectRevisions
from wiredex.projects.domain.revision import Revision
from wiredex.projects.domain.values import (
    MAX_TAG_LENGTH,
    BomLineId,
    NetId,
    PartId,
    ProjectId,
    ProjectName,
    RevisionId,
    RevisionStatus,
    Tag,
    WorkspaceId,
)
from wiredex.projects.infrastructure.orm import (
    bom_designators,
    bom_lines,
    folded_name,
    net_pins,
    nets,
    projects,
    revisions,
)
from wiredex.shared_kernel.domain.trash import TrashPosition
from wiredex.shared_kernel.infrastructure.trash import in_the_trash, live, trash_page

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
        index and agrees with what it enforces (decision 9). A project in the trash keeps its
        name, as the index does (16-soft-delete-and-trash, decision 5)."""
        found = await self._session.execute(self._any().where(folded_name == name.fold()))
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

    async def find(self, text: str, limit: int) -> list[Project]:
        found = await self._session.execute(
            self._mine()
            .where(projects.c.name.ilike(_containing(text), escape=_LIKE_ESCAPE))
            .order_by(*_starting_first(projects.c.name, text), projects.c.id)
            .limit(limit)
        )
        return list(found.scalars())

    async def tag_counts(self) -> list[TagCount]:
        """Each tag once with the number of projects carrying it (requirement 2.6).

        A project holds each tag once, so counting the unnested rows counts projects. Sorted
        here rather than by the database, whose collation may order text differently from the
        code-point order `Tags` keeps a project's own tags in.
        """
        carried = (
            select(func.unnest(projects.c.tags, type_=String(MAX_TAG_LENGTH)).label("tag"))
            .where(projects.c.workspace_id == self._workspace_id, live(projects))
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

    async def trashed(self, before: TrashPosition | None, limit: int) -> list[Project]:
        """One page of the trash, over `ix_projects_trashed` (16's decision 9)."""
        found = await self._session.execute(trash_page(self._any(), projects, before, limit))
        return list(found.scalars())

    async def in_trash(self, project_id: ProjectId) -> Project | None:
        """Locked and fresh, so a restore and a delete for good of one project take turns, and
        the second finds nothing (16's decision 10)."""
        found = await self._session.execute(
            self._any()
            .where(projects.c.id == project_id, in_the_trash(projects))
            .with_for_update()
            .execution_options(**_FRESH)
        )
        return found.scalar_one_or_none()

    async def empty_trash(self) -> int:
        """One `DELETE`; each row it takes is locked and checked again, so a restore racing it
        either wins or finds nothing. Revisions, BOMs and nets go by the keys' cascades."""
        result = await self._session.execute(
            delete(projects).where(
                projects.c.workspace_id == self._workspace_id, in_the_trash(projects)
            )
        )
        return cast("CursorResult[Any]", result).rowcount

    async def kept(self, project_id: ProjectId) -> bool:
        found = await self._session.scalar(
            select(literal(True)).where(
                projects.c.workspace_id == self._workspace_id, projects.c.id == project_id
            )
        )
        return found is not None

    def _mine(self) -> Select[tuple[Project]]:
        """The workspace's live projects: every read but the trash's own and the name check
        goes through here, so a project in the trash is absent everywhere (16's decision 2).
        `locked` locks through it, so a lock taken after a move to the trash finds nothing
        (decision 3)."""
        return self._any().where(live(projects))

    def _any(self) -> Select[tuple[Project]]:
        """The workspace's projects, in the trash or not."""
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
                revisions.c.workspace_id == self._workspace_id,
                revisions.c.id == revision_id,
                _in_a_live_project(),
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

    async def kept(self, revision_id: RevisionId) -> bool:
        found = await self._session.scalar(
            select(literal(True)).where(
                revisions.c.workspace_id == self._workspace_id, revisions.c.id == revision_id
            )
        )
        return found is not None

    async def ref(self, revision_id: RevisionId) -> RevisionRef | None:
        """The revision named by its id alone, joined to its project, in one read (10.2).

        Another workspace's id finds nothing: both tables are filtered on the workspace, and
        the join needs the project of the same workspace, so a revision without one is not
        answered (requirement 11.3).
        """
        found = await self._session.execute(self._ref_query().where(revisions.c.id == revision_id))
        row = found.first()
        return None if row is None else _ref_of(row)

    async def refs(self, revision_ids: Sequence[RevisionId]) -> Mapping[RevisionId, RevisionRef]:
        """The listed revisions' refs in one read, whatever their number (10.4, 10.6)."""
        if not revision_ids:
            return {}
        found = await self._session.execute(
            self._ref_query().where(revisions.c.id.in_(revision_ids))
        )
        refs = [_ref_of(row) for row in found]
        return {ref.revision_id: ref for ref in refs}

    async def drafts(self) -> list[RevisionRef]:
        """Every draft's ref in one read (18-dashboard, decision 3). `_ref_query` joins the
        project and keeps it live, so a draft in the trash, with its project, is left out."""
        found = await self._session.execute(
            self._ref_query().where(revisions.c.status == RevisionStatus.DRAFT)
        )
        return [_ref_of(row) for row in found]

    def _ref_query(self) -> Select[tuple[Any, ...]]:
        # The revision's own columns and its project's name, joined by the composite key, both
        # tables scoped to the workspace.
        return (
            select(
                revisions.c.id,
                revisions.c.label,
                revisions.c.summary,
                revisions.c.status,
                revisions.c.project_id,
                projects.c.name,
            )
            .join(
                projects,
                and_(
                    projects.c.workspace_id == revisions.c.workspace_id,
                    projects.c.id == revisions.c.project_id,
                ),
            )
            .where(revisions.c.workspace_id == self._workspace_id, live(projects))
        )

    def _mine(self) -> Select[tuple[Revision]]:
        """The workspace's revisions of live projects: a revision is in the trash when its
        project is (16-soft-delete-and-trash, decision 2)."""
        return select(Revision).where(
            revisions.c.workspace_id == self._workspace_id, _in_a_live_project()
        )

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

    async def of_revisions(
        self, revision_ids: Sequence[RevisionId]
    ) -> dict[RevisionId, BillOfMaterials]:
        """`of_revision` for many revisions, still two reads whatever their number and size
        (18-dashboard, decision 3): every line oldest first, then every designator, each
        grouped back to its revision and line."""
        if not revision_ids:
            return {}
        lines = await self._session.execute(
            select(bom_lines)
            .where(
                bom_lines.c.workspace_id == self._workspace_id,
                bom_lines.c.revision_id.in_(revision_ids),
            )
            .order_by(bom_lines.c.created_at, bom_lines.c.id)
        )
        held = await self._session.execute(
            select(bom_designators.c.line_id, bom_designators.c.designator).where(
                bom_designators.c.workspace_id == self._workspace_id,
                bom_designators.c.revision_id.in_(revision_ids),
            )
        )
        by_line: dict[UUID, list[Designator]] = {}
        for line_id, designator in held.tuples():
            by_line.setdefault(line_id, []).append(designator)
        by_revision: dict[RevisionId, list[BomLine]] = {
            revision_id: [] for revision_id in revision_ids
        }
        for row in lines:
            line = _line_of(row, by_line.get(row.id, ()))
            by_revision[line.revision_id].append(line)
        return {
            revision_id: BillOfMaterials(revision_id, tuple(found))
            for revision_id, found in by_revision.items()
        }

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
        # Every project, the trash's included: a BOM there still names its parts, so a project
        # restored later finds each of them (16-soft-delete-and-trash, decision 4).
        rows = await self._session.execute(
            select(
                projects.c.id,
                projects.c.name,
                revisions.c.id,
                revisions.c.label,
                projects.c.trashed_at,
            )
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
            BomUse(
                ProjectId(project_id),
                name,
                RevisionId(revision_id),
                label,
                in_trash=trashed_at is not None,
            )
            for project_id, name, revision_id, label, trashed_at in rows.tuples()
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


class SqlNets:
    """A revision's nets and their references (11-netlist-editor, decisions 2 and 8)."""

    def __init__(self, session: AsyncSession, workspace_id: WorkspaceId) -> None:
        self._session = session
        self._workspace_id = workspace_id

    async def of_revision(self, revision_id: RevisionId) -> Netlist:
        """Two reads whatever the size: the nets oldest first, the id breaking a tie on the
        clock so a fork's copies keep the source's order, then every reference of the revision,
        grouped per net."""
        rows = await self._session.execute(
            select(nets)
            .where(nets.c.workspace_id == self._workspace_id, nets.c.revision_id == revision_id)
            .order_by(nets.c.created_at, nets.c.id)
        )
        held = await self._session.execute(
            select(net_pins.c.net_id, net_pins.c.designator, net_pins.c.pin).where(
                net_pins.c.workspace_id == self._workspace_id,
                net_pins.c.revision_id == revision_id,
            )
        )
        by_net: dict[UUID, list[PinReference]] = {}
        for net_id, designator, pin in held.tuples():
            by_net.setdefault(net_id, []).append(PinReference(designator, pin))
        return Netlist(revision_id, tuple(_net_of(row, by_net.get(row.id, ())) for row in rows))

    async def add(self, net: Net) -> None:
        await self.add_all((net,))

    async def add_all(self, added: Sequence[Net]) -> None:
        """One statement for the nets and one for their references, whatever their number.
        The flush first, as `SqlBomLines.add_all` does, for a fork's pending revision."""
        await self._session.flush()
        if not added:
            return
        await self._session.execute(insert(nets), [self._row_of(net) for net in added])
        await self._insert_pins(added)

    async def update(self, before: Net, after: Net) -> None:
        """The name, color and notes, then the references by a delete and one insert: nothing
        hangs off a reference, so rewriting a net's few rows is the plain way (decision 8)."""
        content = after.content
        await self._session.execute(
            update_rows(nets)
            .where(nets.c.workspace_id == self._workspace_id, nets.c.id == after.id)
            .values(name=content.name, color=content.color, notes=content.notes)
        )
        if before.content.pins == content.pins:
            return
        await self._session.execute(
            delete(net_pins).where(
                net_pins.c.workspace_id == self._workspace_id,
                net_pins.c.revision_id == after.revision_id,
                net_pins.c.net_id == after.id,
            )
        )
        await self._insert_pins((after,))

    async def uses_of_part(self, part_id: PartId) -> list[PinUse]:
        """Every reference, in any revision, to a designator whose BOM line holds the part, in
        one join (12-wiring-validation decision 7). The designator's order is the canonical one,
        R2 before R10, which text can't give, so the rows are sorted here."""
        same_revision = [
            net_pins.c.workspace_id == bom_designators.c.workspace_id,
            net_pins.c.revision_id == bom_designators.c.revision_id,
        ]
        rows = await self._session.execute(
            select(
                projects.c.id.label("project_id"),
                projects.c.name.label("project_name"),
                revisions.c.id.label("revision_id"),
                revisions.c.label,
                revisions.c.status,
                revisions.c.created_at,
                net_pins.c.designator,
                net_pins.c.pin,
                nets.c.id.label("net_id"),
                nets.c.name.label("net_name"),
                nets.c.color,
                nets.c.created_at.label("net_created_at"),
            )
            .select_from(net_pins)
            .join(
                bom_designators,
                and_(*same_revision, net_pins.c.designator == bom_designators.c.designator),
            )
            .join(
                bom_lines,
                and_(
                    bom_lines.c.workspace_id == bom_designators.c.workspace_id,
                    bom_lines.c.id == bom_designators.c.line_id,
                ),
            )
            .join(
                nets,
                and_(
                    nets.c.workspace_id == net_pins.c.workspace_id, nets.c.id == net_pins.c.net_id
                ),
            )
            .join(
                revisions,
                and_(
                    revisions.c.workspace_id == net_pins.c.workspace_id,
                    revisions.c.id == net_pins.c.revision_id,
                ),
            )
            .join(
                projects,
                and_(
                    projects.c.workspace_id == revisions.c.workspace_id,
                    projects.c.id == revisions.c.project_id,
                ),
            )
            .where(
                net_pins.c.workspace_id == self._workspace_id,
                bom_lines.c.part_id == part_id,
                live(projects),
            )
        )
        found = sorted(
            rows,
            key=lambda row: (
                row.project_name.fold(),
                row.created_at,
                row.revision_id,
                row.designator,
                row.pin.sort_key(),
                row.net_created_at,
                row.net_id,
            ),
        )
        return [
            PinUse(
                ProjectId(row.project_id),
                row.project_name,
                RevisionId(row.revision_id),
                row.label,
                row.status,
                row.designator,
                row.pin,
                NetId(row.net_id),
                row.net_name,
                row.color,
            )
            for row in found
        ]

    async def remove(self, net: Net) -> None:
        # Its references go with it, by the composite key's ON DELETE CASCADE.
        await self._session.execute(
            delete(nets).where(nets.c.workspace_id == self._workspace_id, nets.c.id == net.id)
        )

    async def _insert_pins(self, written: Iterable[Net]) -> None:
        rows = [
            {
                "workspace_id": net.workspace_id,
                "revision_id": net.revision_id,
                "net_id": net.id,
                "designator": reference.designator,
                "pin": reference.pin,
            }
            for net in written
            for reference in net.content.pins
        ]
        if rows:
            await self._session.execute(insert(net_pins), rows)

    def _row_of(self, net: Net) -> dict[str, Any]:
        content = net.content
        return {
            "id": net.id,
            "workspace_id": net.workspace_id,
            "revision_id": net.revision_id,
            "name": content.name,
            "color": content.color,
            "notes": content.notes,
            "created_at": net.created_at,
        }


def _in_a_live_project() -> ColumnElement[bool]:
    """The revision's project isn't in the trash: correlated to the revision row, over the
    projects' primary key."""
    return (
        select(literal(1))
        .where(
            projects.c.workspace_id == revisions.c.workspace_id,
            projects.c.id == revisions.c.project_id,
            live(projects),
        )
        .correlate(revisions)
        .exists()
    )


def _ref_of(row: Row[Any]) -> RevisionRef:
    """A `RevisionRef` from a joined row: its columns come back through their types, so the
    label, summary, status and name are already the value objects."""
    return RevisionRef(
        revision_id=RevisionId(row.id),
        label=row.label,
        summary=row.summary,
        status=row.status,
        project_id=ProjectId(row.project_id),
        project_name=row.name,
    )


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


def _starting_first(title: ColumnElement[Any], text: str) -> tuple[ColumnElement[Any], ...]:
    """A find's order (19-command-palette, decision 2): the titles starting with the text
    first, then the rest, each by the title folded. `COLLATE "C"` orders by code point, as
    Python's sort does, whatever collation the database was created with."""
    starting = f"{text.translate(_LIKE_WILDCARDS)}%"
    return (
        title.ilike(starting, escape=_LIKE_ESCAPE).desc(),
        func.lower(title).collate("C"),
    )


def _net_of(row: Row[Any], references: Iterable[PinReference]) -> Net:
    content = NetContent(row.name, row.color, row.notes, NetPins.of(references))
    return Net(
        NetId(row.id),
        WorkspaceId(row.workspace_id),
        RevisionId(row.revision_id),
        content,
        row.created_at,
    )
