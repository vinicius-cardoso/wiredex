"""In-memory stand-ins for the projects ports, shared by the use-case tests.

Each store is one workspace's rows, because that is what a real projects unit of work sees
(ADR 0007): the workspace it was opened for is recorded rather than filtered on, so a test can
still assert that a use case scoped itself to the caller's bench.

The stores do what the schema does on its own: removing a project takes its revisions (the
cascade), and removing a revision clears every `forked_from` naming it (`SET NULL`). They
write straight through and count commits, so "nothing written" is something a test can see,
and every read is counted, so a test can tell a page costs the same whatever its size.
"""

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Self
from uuid import uuid7

from support.identity import ManualClock, NewIds
from wiredex.projects.application.ports import RevisionContent, TagCount
from wiredex.projects.application.projects import (
    CreateProject,
    DeleteProject,
    GetProject,
    ListProjects,
    ListProjectTags,
    UpdateProject,
)
from wiredex.projects.application.revisions import (
    AddRevision,
    DeleteRevision,
    ForkRevision,
    GetRevision,
    UpdateRevision,
)
from wiredex.projects.domain.filter import ProjectFilter
from wiredex.projects.domain.project import Project
from wiredex.projects.domain.project_revisions import ProjectRevisions
from wiredex.projects.domain.revision import Revision
from wiredex.projects.domain.values import (
    Description,
    ProjectId,
    ProjectName,
    RevisionId,
    RevisionLabel,
    RevisionStatus,
    Tags,
    WorkspaceId,
)

NOW = datetime(2026, 9, 27, 10, 0, tzinfo=UTC)
BENCH = WorkspaceId(uuid7())


class InMemoryRevisions:
    def __init__(self) -> None:
        self.saved: dict[RevisionId, Revision] = {}
        self.reads = 0

    async def add(self, revision: Revision) -> None:
        self.saved[revision.id] = revision

    async def get(self, revision_id: RevisionId) -> Revision | None:
        self.reads += 1
        return self.saved.get(revision_id)

    async def of_project(self, project_id: ProjectId) -> ProjectRevisions:
        self.reads += 1
        return self._of(project_id)

    async def of_projects(
        self, project_ids: Sequence[ProjectId]
    ) -> Mapping[ProjectId, ProjectRevisions]:
        self.reads += 1
        return {project_id: self._of(project_id) for project_id in project_ids}

    async def remove(self, revision: Revision) -> None:
        del self.saved[revision.id]
        for other in self.saved.values():
            if other.forked_from == revision.id:
                other.forked_from = None

    def take_project(self, project_id: ProjectId) -> None:
        """The cascade from a deleted project."""
        for revision in [r for r in self.saved.values() if r.project_id == project_id]:
            del self.saved[revision.id]

    def _of(self, project_id: ProjectId) -> ProjectRevisions:
        return ProjectRevisions(
            tuple(revision for revision in self.saved.values() if revision.project_id == project_id)
        )


class InMemoryProjects:
    """One workspace's projects. It records which projects were locked, in order, so a test
    can tell a change to a project's revisions took the project's lock."""

    def __init__(self, revisions: InMemoryRevisions) -> None:
        self.saved: dict[ProjectId, Project] = {}
        self.locks: list[ProjectId] = []
        self.reads = 0
        self._revisions = revisions

    async def add(self, project: Project) -> None:
        self.saved[project.id] = project

    async def get(self, project_id: ProjectId) -> Project | None:
        self.reads += 1
        return self.saved.get(project_id)

    async def locked(self, project_id: ProjectId) -> Project | None:
        self.reads += 1
        project = self.saved.get(project_id)
        if project is not None:
            self.locks.append(project_id)
        return project

    async def named(self, name: ProjectName) -> Project | None:
        self.reads += 1
        holders = (p for p in self.saved.values() if p.name.fold() == name.fold())
        return next(holders, None)

    async def matching(self, wanted: ProjectFilter) -> list[Project]:
        self.reads += 1
        return [project for project in self.saved.values() if wanted.matches(project)]

    async def tag_counts(self) -> list[TagCount]:
        self.reads += 1
        counts = Counter(tag for project in self.saved.values() for tag in project.tags.values)
        return [TagCount(tag, counts[tag]) for tag in sorted(counts, key=lambda tag: tag.value)]

    async def remove(self, project: Project) -> None:
        del self.saved[project.id]
        self._revisions.take_project(project.id)


class InMemoryProjectsUnitOfWork:
    """A unit of work over shared in-memory stores; counts commits and reads, and records who
    it was opened for.

    The repositories are plain attributes, which satisfy the read-only properties the
    `ProjectsUnitOfWork` protocol declares. `revision_contents` is settable, so a fork test
    registers what it wants copied, as 09's unit of work will register its BOM lines.
    """

    def __init__(self) -> None:
        self.revisions = InMemoryRevisions()
        self.projects = InMemoryProjects(self.revisions)
        self.revision_contents: Sequence[RevisionContent] = ()
        self.commits = 0
        self.opened_for: list[WorkspaceId] = []

    @property
    def reads(self) -> int:
        return self.projects.reads + self.revisions.reads

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

    async def clear(self) -> None:
        self.projects.saved.clear()
        self.revisions.saved.clear()


@dataclass(frozen=True, slots=True)
class Copy:
    """One `copy` a content was asked for, and how many commits had happened by then."""

    content: str
    source: RevisionId
    target: RevisionId
    commits_before: int


@dataclass
class RecordingContent:
    """A revision content that only records the copies asked of it, into a log several
    contents can share, so a test sees the order they ran in."""

    work: InMemoryProjectsUnitOfWork
    name: str = "content"
    log: list[Copy] = field(default_factory=list)

    async def copy(self, source: Revision, target: Revision) -> None:
        self.log.append(Copy(self.name, source.id, target.id, self.work.commits))


class CopyFailedError(RuntimeError):
    """What `FailingContent` raises: no projects rule, so nothing maps it to a refusal."""


class FailingContent:
    """A revision content whose copy always fails, as a broken write in 09 or 11 would."""

    async def copy(self, source: Revision, target: Revision) -> None:
        raise CopyFailedError(f"copying {source.label} into {target.label} failed")


class World:
    """The projects fakes over an empty bench, and the use cases built on them.

    Seeds are written straight to the stores, not through use cases: a test of one use case
    shouldn't depend on another one working, and a revision in a status other than draft can't
    be made through the use cases before 10-build-lifecycle.
    """

    def __init__(self) -> None:
        self.work = InMemoryProjectsUnitOfWork()
        self.clock = ManualClock(NOW)
        self.ids = NewIds()
        factory = self.work.for_workspace
        self.create_project = CreateProject(factory, self.clock, self.ids)
        self.update_project = UpdateProject(factory, self.clock)
        self.delete_project = DeleteProject(factory)
        self.get_project = GetProject(factory)
        self.list_projects = ListProjects(factory)
        self.list_project_tags = ListProjectTags(factory)
        self.add_revision = AddRevision(factory, self.clock, self.ids)
        self.fork_revision = ForkRevision(factory, self.clock, self.ids)
        self.update_revision = UpdateRevision(factory, self.clock)
        self.delete_revision = DeleteRevision(factory, self.clock)
        self.get_revision = GetRevision(factory)

    def hold_project(
        self,
        name: str,
        *,
        tags: Sequence[str] = (),
        description: str | None = None,
        minutes: int = 0,
        revision: str | None = "A",
    ) -> Project:
        """A project last updated `minutes` after NOW, with a first draft revision unless
        `revision` is None."""
        when = NOW + timedelta(minutes=minutes)
        project = Project(
            id=ProjectId(uuid7()),
            workspace_id=BENCH,
            name=ProjectName(name),
            description=None if description is None else Description(description),
            tags=Tags.of(tags),
            created_at=when,
            updated_at=when,
        )
        self.work.projects.saved[project.id] = project
        if revision is not None:
            self.hold_revision(project, revision, minutes=minutes)
        return project

    def hold_revision(
        self,
        project: Project,
        label: str,
        *,
        status: RevisionStatus = RevisionStatus.DRAFT,
        minutes: int = 0,
    ) -> Revision:
        """A draft (or `status`) revision of the project, forked from nothing, with no summary
        or notes, created and last updated `minutes` after NOW."""
        when = NOW + timedelta(minutes=minutes)
        revision = Revision(
            id=RevisionId(uuid7()),
            workspace_id=project.workspace_id,
            project_id=project.id,
            label=RevisionLabel(label),
            summary=None,
            notes=None,
            status=status,
            forked_from=None,
            created_at=when,
            updated_at=when,
        )
        self.work.revisions.saved[revision.id] = revision
        return revision
