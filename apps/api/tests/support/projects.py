"""In-memory stand-ins for the projects ports, shared by the use-case tests.

Each store is one workspace's rows, because that is what a real projects unit of work sees
(ADR 0007): the workspace it was opened for is recorded rather than filtered on, so a test can
still assert that a use case scoped itself to the caller's bench.

The stores do what the schema does on its own: removing a project takes its revisions (the
cascade), removing a revision takes its BOM lines and clears every `forked_from` naming it
(`SET NULL`). They write straight through and count commits, so "nothing written" is
something a test can see, and every read is counted, so a test can tell a page costs the same
whatever its size.
"""

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Self
from uuid import uuid7

from support.identity import ManualClock, NewIds
from wiredex.projects.api.router import ProjectsUseCases
from wiredex.projects.application.bom import (
    AddBomLine,
    GetBom,
    ListPartUses,
    RemoveBomLine,
    UpdateBomLine,
)
from wiredex.projects.application.ports import BomUse, BomUses, RevisionContent, TagCount
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
from wiredex.projects.domain.bom import BillOfMaterials, BomLine
from wiredex.projects.domain.filter import ProjectFilter
from wiredex.projects.domain.project import Project
from wiredex.projects.domain.project_revisions import ProjectRevisions
from wiredex.projects.domain.revision import Revision
from wiredex.projects.domain.shortage import PartFacts
from wiredex.projects.domain.values import (
    BomLineId,
    Description,
    PartId,
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


class InMemoryBomLines:
    """One workspace's BOM lines, read back in the order `SqlBomLines` reads them.

    `uses_of` names projects and revisions, as the SQL joins them, so the unit of work hands
    it the other two stores' rows.
    """

    def __init__(
        self, projects: Mapping[ProjectId, Project], revisions: Mapping[RevisionId, Revision]
    ) -> None:
        self.saved: dict[BomLineId, BomLine] = {}
        self.reads = 0
        self._projects = projects
        self._revisions = revisions

    async def of_revision(self, revision_id: RevisionId) -> BillOfMaterials:
        self.reads += 1
        return BillOfMaterials(revision_id, tuple(self._of(revision_id)))

    async def add(self, line: BomLine) -> None:
        self.saved[line.id] = line

    async def add_all(self, lines: Sequence[BomLine]) -> None:
        for line in lines:
            self.saved[line.id] = line

    async def update(self, before: BomLine, after: BomLine) -> None:
        assert before.id == after.id
        self.saved[after.id] = after

    async def remove(self, line: BomLine) -> None:
        del self.saved[line.id]

    async def uses_of(self, part_id: PartId, limit: int) -> BomUses:
        self.reads += 1
        naming = {
            line.revision_id for line in self.saved.values() if line.content.part_id == part_id
        }
        revisions = sorted(
            (self._revisions[revision_id] for revision_id in naming),
            key=lambda revision: (
                self._projects[revision.project_id].name.fold(),
                revision.created_at,
                revision.id,
            ),
        )
        uses = tuple(
            BomUse(
                revision.project_id,
                self._projects[revision.project_id].name,
                revision.id,
                revision.label,
            )
            for revision in revisions[:limit]
        )
        return BomUses(uses, len(revisions))

    def take_revision(self, revision_id: RevisionId) -> None:
        """The cascade from a deleted revision."""
        for line in self._of(revision_id):
            del self.saved[line.id]

    def _of(self, revision_id: RevisionId) -> list[BomLine]:
        lines = [line for line in self.saved.values() if line.revision_id == revision_id]
        return sorted(lines, key=lambda line: (line.created_at, line.id))


class InMemoryRevisions:
    def __init__(self) -> None:
        self.saved: dict[RevisionId, Revision] = {}
        self.reads = 0
        self.lines = InMemoryBomLines({}, self.saved)

    async def add(self, revision: Revision) -> None:
        self.saved[revision.id] = revision

    async def get(self, revision_id: RevisionId) -> Revision | None:
        self.reads += 1
        return self.saved.get(revision_id)

    async def project_of(self, revision_id: RevisionId) -> ProjectId | None:
        self.reads += 1
        revision = self.saved.get(revision_id)
        return None if revision is None else revision.project_id

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
        self.lines.take_revision(revision.id)
        for other in self.saved.values():
            if other.forked_from == revision.id:
                other.forked_from = None

    def take_project(self, project_id: ProjectId) -> None:
        """The cascade from a deleted project, and from its revisions to their lines."""
        for revision in [r for r in self.saved.values() if r.project_id == project_id]:
            del self.saved[revision.id]
            self.lines.take_revision(revision.id)

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
    `ProjectsUnitOfWork` and `BomUnitOfWork` protocols declare. `revision_contents` is
    settable, so a fork test registers what it wants copied.
    """

    def __init__(self) -> None:
        self.revisions = InMemoryRevisions()
        self.projects = InMemoryProjects(self.revisions)
        self.bom_lines = InMemoryBomLines(self.projects.saved, self.revisions.saved)
        # The revisions' cascade reaches the same lines the unit of work hands out.
        self.revisions.lines = self.bom_lines
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
        self.bom_lines.saved.clear()


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


class FakePartLookup:
    """Projects' `PartLookup` over a dict of facts; counts its calls and what they asked."""

    def __init__(self) -> None:
        self.facts: dict[PartId, PartFacts] = {}
        # Each call's workspace and part ids, so a test sees what was asked and for which bench.
        self.asked: list[tuple[WorkspaceId, tuple[PartId, ...]]] = []

    async def describe(
        self, workspace_id: WorkspaceId, part_ids: Sequence[PartId]
    ) -> Mapping[PartId, PartFacts]:
        self.asked.append((workspace_id, tuple(part_ids)))
        return {part_id: self.facts[part_id] for part_id in part_ids if part_id in self.facts}

    def hold(self, name: str, *, tracked: bool = False, not_stocked: bool = False) -> PartId:
        """A part the catalog holds, named and flagged, with no other details."""
        part_id = PartId(uuid7())
        self.facts[part_id] = PartFacts(part_id, name, None, None, None, tracked, not_stocked)
        return part_id


class FakeStockLevels:
    """Projects' `StockLevels` over a dict of available counts; counts its calls."""

    def __init__(self) -> None:
        self.available_by_part: dict[PartId, int] = {}
        # Each call's workspace and part ids, so a test sees what was asked and for which bench.
        self.asked: list[tuple[WorkspaceId, tuple[PartId, ...]]] = []

    async def available(
        self, workspace_id: WorkspaceId, part_ids: Sequence[PartId]
    ) -> Mapping[PartId, int]:
        self.asked.append((workspace_id, tuple(part_ids)))
        held = self.available_by_part
        return {part_id: held[part_id] for part_id in part_ids if part_id in held}


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
        self.parts = FakePartLookup()
        self.stock = FakeStockLevels()
        self.get_bom = GetBom(factory, self.parts, self.stock)
        self.add_bom_line = AddBomLine(factory, self.parts, self.clock, self.ids)
        self.update_bom_line = UpdateBomLine(factory, self.parts, self.clock)
        self.remove_bom_line = RemoveBomLine(factory, self.clock)
        self.list_part_uses = ListPartUses(factory)

    def projects_use_cases(self) -> ProjectsUseCases:
        """What `create_router` takes, so the API test mounts these same fakes."""
        return ProjectsUseCases(
            create_project=self.create_project,
            update_project=self.update_project,
            delete_project=self.delete_project,
            get_project=self.get_project,
            list_projects=self.list_projects,
            list_project_tags=self.list_project_tags,
            add_revision=self.add_revision,
            fork_revision=self.fork_revision,
            update_revision=self.update_revision,
            delete_revision=self.delete_revision,
            get_revision=self.get_revision,
        )

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
