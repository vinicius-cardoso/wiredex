"""The sample projects a demo bench holds, and putting them back (ADR 0007, decision 16).

A guest may create, rename, fork and delete whatever they like in their own bench, so restoring
is not a merge: the workspace's projects are cleared and the samples written again, which is
what makes a demo bench look the same every morning (requirements 9.1 and 9.2).

The samples go in through `CreateProject`, `UpdateRevision` and `ForkRevision`, the use cases
the web calls, so a rule that stopped accepting a sample would fail the nightly job rather
than seed something the app can't hold. A project starts with revision A (decision 2), so the
first sample revision is written as an edit of it, and every later one as a fork, which is
what gives a guest a fork to look at and another to try.

Projects run last in a reset, after the catalog and the inventory: 09's sample BOM lines will
point at the sample parts. Nothing here reads another module yet.
"""

from collections.abc import Callable
from dataclasses import dataclass

from wiredex.projects.application.ports import NewRevision, ProjectsUnitOfWork
from wiredex.projects.application.projects import CreateProject
from wiredex.projects.application.revisions import ForkRevision, UpdateRevision
from wiredex.projects.domain.project import ProjectDetails
from wiredex.projects.domain.revision import Revision, RevisionDetails
from wiredex.projects.domain.values import (
    Description,
    Notes,
    ProjectName,
    RevisionLabel,
    Summary,
    Tags,
    WorkspaceId,
)

# A factory over the workspace, like every projects use case's, so the clear scopes to the one
# bench (ADR 0007).
type UnitOfWorkFactory = Callable[[WorkspaceId], ProjectsUnitOfWork]


@dataclass(frozen=True, slots=True)
class SampleRevision:
    """A project's first revision, in the words the edit dialog would hold."""

    label: str
    summary: str
    notes: str | None = None


@dataclass(frozen=True, slots=True)
class SampleFork:
    """A later revision, forked from the sample revision labelled `source`."""

    source: str
    label: str
    summary: str
    notes: str | None = None


@dataclass(frozen=True, slots=True)
class SampleProject:
    """A sample project: its details, its first revision, and the forks that follow it."""

    name: str
    description: str
    tags: tuple[str, ...]
    first: SampleRevision
    forks: tuple[SampleFork, ...] = ()


# Small on purpose, and still enough to show what projects do: tags two projects share and one
# each keeps, a description, and a revision B forked from A with a note on why.
SAMPLE_PROJECTS: tuple[SampleProject, ...] = (
    SampleProject(
        "Weather station",
        "A BME280 on an ESP32, logging temperature, humidity and pressure every five minutes.",
        ("esp32", "i2c", "outdoor"),
        first=SampleRevision("A", "breadboard"),
        forks=(
            SampleFork(
                "A",
                "B",
                "perfboard",
                notes=(
                    "The sensor moves off the board, on a 20 cm cable: next to the ESP32 it "
                    "read about 2 °C high from the module's own heat."
                ),
            ),
        ),
    ),
    SampleProject(
        "Greenhouse controller",
        "Waters the tomatoes when the soil dries out.",
        ("esp32", "relay"),
        first=SampleRevision("A", "breadboard"),
    ),
)


class RestoreSampleProjects:
    """Puts one demo bench's sample projects back, whatever the guest did to them.

    Part of the nightly `wiredex demo reset` and of `wiredex demo invite` (ADR 0011, decision
    16). Which workspaces are demo benches is identity's to answer, so the composition root
    asks there and hands the ids here: projects imports no other module.
    """

    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        create_project: CreateProject,
        update_revision: UpdateRevision,
        fork_revision: ForkRevision,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._create_project = create_project
        self._update_revision = update_revision
        self._fork_revision = fork_revision

    async def __call__(self, workspace_id: WorkspaceId) -> int:
        """Restores the bench's sample projects and returns how many it ended with.

        The clear is one transaction; each project, edit and fork then goes in through its own
        use case, each its own transaction, as the web writes them. The workspace it is opened
        for is the only one any step can touch (ADR 0007).
        """
        await self._clear(workspace_id)
        for sample in SAMPLE_PROJECTS:
            await self._write(workspace_id, sample)
        return len(SAMPLE_PROJECTS)

    async def _clear(self, workspace_id: WorkspaceId) -> None:
        async with self._unit_of_work(workspace_id) as work:
            await work.clear()
            await work.commit()

    async def _write(self, workspace_id: WorkspaceId, sample: SampleProject) -> None:
        details = ProjectDetails(
            name=ProjectName(sample.name),
            description=Description(sample.description),
            tags=Tags.of(sample.tags),
        )
        view = await self._create_project(workspace_id, details)
        # A new project holds revision A and nothing else (decision 2).
        (created,) = view.revisions.items
        first = await self._update_revision(
            workspace_id,
            created.id,
            RevisionDetails(
                RevisionLabel(sample.first.label),
                Summary(sample.first.summary),
                _notes(sample.first.notes),
            ),
        )
        by_label: dict[str, Revision] = {first.label.value: first}
        for fork in sample.forks:
            by_label[fork.label] = await self._fork_revision(
                workspace_id,
                by_label[fork.source].id,
                NewRevision(RevisionLabel(fork.label), Summary(fork.summary), _notes(fork.notes)),
            )


def _notes(text: str | None) -> Notes | None:
    return None if text is None else Notes(text)
