"""Revisions: add one, fork one, edit one, delete one, and read one.

Every change that looks across a project's revisions (which label is free, how many are left)
locks the project first and reads the siblings after (decision 15), so two requests take turns
instead of both taking label C or both deleting one of the last two revisions. The revision a
change started from is then looked for again among the siblings, because it may have been
deleted while the change waited for the lock.
"""

from wiredex.projects.application.ports import NewRevision, ProjectsUnitOfWork
from wiredex.projects.application.projects import UnitOfWorkFactory, lock_project
from wiredex.projects.domain.errors import DuplicateRevisionLabelError, RevisionNotFoundError
from wiredex.projects.domain.project import Project
from wiredex.projects.domain.project_revisions import ProjectRevisions
from wiredex.projects.domain.revision import Revision, RevisionDetails
from wiredex.projects.domain.values import ProjectId, RevisionId, RevisionLabel, WorkspaceId
from wiredex.shared_kernel.application.ports import Clock, IdGenerator


class AddRevision:
    """A new draft of a project, with the label given or suggested (requirement 4.1)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory, clock: Clock, ids: IdGenerator) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._ids = ids

    async def __call__(
        self, workspace_id: WorkspaceId, project_id: ProjectId, new: NewRevision
    ) -> Revision:
        async with self._unit_of_work(workspace_id) as work:
            project = await lock_project(work, project_id)
            siblings = await work.revisions.of_project(project.id)
            label = _label_for(project, siblings, new.label)
            revision = Revision.draft(
                RevisionId(self._ids.new_id()), project, new.details_with(label), self._clock.now()
            )
            await work.revisions.add(revision)
            await work.commit()
            return revision


class ForkRevision:
    """A draft revision started from another of the same project, carrying its content.

    The revision row is this spec's. What a revision holds is copied by the contents the unit
    of work carries, in their order, before the one commit (decision 6): none here, 09's BOM
    lines and 11's nets later, without this class changing (requirement 6.7).
    """

    def __init__(self, unit_of_work: UnitOfWorkFactory, clock: Clock, ids: IdGenerator) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._ids = ids

    async def __call__(
        self, workspace_id: WorkspaceId, source_id: RevisionId, new: NewRevision
    ) -> Revision:
        async with self._unit_of_work(workspace_id) as work:
            found = await load_revision(work, source_id)
            project = await lock_project(work, found.project_id)
            siblings = await work.revisions.of_project(project.id)
            # A source deleted while the fork waited for the lock is a 404, never a fork
            # pointing at nothing.
            source = _again(siblings, source_id)
            label = _label_for(project, siblings, new.label)
            fork = Revision.fork_of(
                source, RevisionId(self._ids.new_id()), new.details_with(label), self._clock.now()
            )
            await work.revisions.add(fork)
            for content in work.revision_contents:
                await content.copy(source, fork)
            # Leaving the block without it, whatever a content raised, keeps neither the fork
            # nor any copy (requirement 6.4).
            await work.commit()
            return fork


class UpdateRevision:
    """Replaces a revision's label, summary and notes whole, in any status (requirement 4.8)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory, clock: Clock) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    async def __call__(
        self, workspace_id: WorkspaceId, revision_id: RevisionId, details: RevisionDetails
    ) -> Revision:
        async with self._unit_of_work(workspace_id) as work:
            revision = await load_revision(work, revision_id)
            # Only a new label has to be checked against the siblings; a summary or notes edit
            # needs no turn of its own.
            if details.label != revision.label:
                project = await lock_project(work, revision.project_id)
                siblings = await work.revisions.of_project(project.id)
                revision = _again(siblings, revision_id)
                _label_for(project, siblings, details.label, renaming=revision)
            if revision.revise(details, self._clock.now()):
                await work.commit()
            return revision


class DeleteRevision:
    """A draft revision of a project that keeps another (requirements 5.1 to 5.4)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory, clock: Clock) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    async def __call__(self, workspace_id: WorkspaceId, revision_id: RevisionId) -> None:
        async with self._unit_of_work(workspace_id) as work:
            found = await load_revision(work, revision_id)
            project = await lock_project(work, found.project_id)
            siblings = await work.revisions.of_project(project.id)
            revision = _again(siblings, revision_id)
            siblings.ensure_removable(revision)
            await work.revisions.remove(revision)
            # A deleted revision leaves no date behind, so the project keeps the moment for
            # the list's last activity (decision 11).
            project.touch(self._clock.now())
            await work.commit()


class GetRevision:
    """One revision, or a 404: what `files` asks, through bootstrap, before attaching to it."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId, revision_id: RevisionId) -> Revision:
        async with self._unit_of_work(workspace_id) as work:
            return await load_revision(work, revision_id)


async def load_revision(work: ProjectsUnitOfWork, revision_id: RevisionId) -> Revision:
    """The revision, or a 404. Another workspace's id is simply not found (requirement 8.2)."""
    revision = await work.revisions.get(revision_id)
    if revision is None:
        raise RevisionNotFoundError("that revision doesn't exist")
    return revision


def _again(siblings: ProjectRevisions, revision_id: RevisionId) -> Revision:
    """The revision as the siblings read under the lock have it, or a 404 if it went."""
    for revision in siblings.items:
        if revision.id == revision_id:
            return revision
    raise RevisionNotFoundError("that revision doesn't exist")


def _label_for(
    project: Project,
    siblings: ProjectRevisions,
    asked: RevisionLabel | None,
    renaming: Revision | None = None,
) -> RevisionLabel:
    """`siblings.label_for`, its refusal naming the project, which the siblings can't see."""
    try:
        return siblings.label_for(asked, renaming)
    except DuplicateRevisionLabelError as error:
        # Only an asked label can be taken; the holder's own spelling is what the owner sees
        # on the page.
        wanted = asked.fold() if asked is not None else None
        held = next(
            revision.label
            for revision in siblings.items
            if revision is not renaming and revision.label.fold() == wanted
        )
        raise DuplicateRevisionLabelError(
            f"{project.name} already has a revision {held}"
        ) from error
