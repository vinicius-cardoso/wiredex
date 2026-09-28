"""Projects in PostgreSQL: one repository per port, each bound to one workspace.

Every statement filters `workspace_id` itself, the first of ADR 0007's two gates, even though
the policies on these tables already hide another workspace's rows: the filter is what makes a
query's scope readable, and what still holds if a connection ever runs without the setting the
policies read.

The project row is also the lock that makes changes to one project's revisions take turns
(decision 15). `locked` and `of_project` refresh what the session already holds, because a use
case reads a revision before it waits for that lock, and what it read may have changed by the
time the lock is granted.
"""

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import Select, String, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from wiredex.projects.application.ports import TagCount
from wiredex.projects.domain.filter import ProjectFilter
from wiredex.projects.domain.project import Project
from wiredex.projects.domain.project_revisions import ProjectRevisions
from wiredex.projects.domain.revision import Revision
from wiredex.projects.domain.values import (
    MAX_TAG_LENGTH,
    ProjectId,
    ProjectName,
    RevisionId,
    Tag,
    WorkspaceId,
)
from wiredex.projects.infrastructure.orm import folded_name, projects, revisions

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
        found = await self._session.execute(self._mine().where(revisions.c.id == revision_id))
        return found.scalar_one_or_none()

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


def _containing(text: str) -> str:
    return f"%{text.translate(_LIKE_WILDCARDS)}%"
