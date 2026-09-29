"""The sample projects a demo bench holds, and putting them back (ADR 0007, decision 16).

A guest may create, rename, fork and delete whatever they like in their own bench, so restoring
is not a merge: the workspace's projects are cleared and the samples written again, which is
what makes a demo bench look the same every morning (requirements 9.1 and 9.2).

The samples go in through `CreateProject`, `UpdateRevision` and `ForkRevision`, the use cases
the web calls, so a rule that stopped accepting a sample would fail the nightly job rather
than seed something the app can't hold. A project starts with revision A (decision 2), so the
first sample revision is written as an edit of it, and every later one as a fork, which is
what gives a guest a fork to look at and another to try.

Projects run last in a reset, after the catalog and the inventory, because the sample BOM
lines point at the sample parts (09's requirement 10.2). A line names its part by its sample
name, and the composition root resolves those names to the ids the catalog's restore just
minted and hands them here through `DemoParts`, so projects reads no other module. Each line
goes in through `AddBomLine`, as a line from the editor does; a revision's lines are added
before it is forked, so a fork copies them as any fork does, and then gets its own.

Once the projects and their BOMs are back, the bench's sample *Greenhouse controller* `A` is
reserved through `ReserveRevision`, with no named units, in a unit of work of its own (10's
requirement 12, decision 9). Going through the reserve use case means the demo can only ever
show a reservation the product could make: the automatic choice sets aside the bench's one
ESP32 board and the greenhouse's other parts, so both *Weather station* revisions then report
their ESP32 short, one board being tied up in the greenhouse. A second reset or a fresh invite
restores the same reservation, whatever the guest reserved, built, cancelled or dismantled,
because the reserve runs against the freshly restored draft (requirement 12.2).
"""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

from wiredex.projects.application.bom import AddBomLine
from wiredex.projects.application.lifecycle import ReserveRevision
from wiredex.projects.application.ports import NewBomLine, NewRevision, ProjectsUnitOfWork
from wiredex.projects.application.projects import CreateProject
from wiredex.projects.application.revisions import ForkRevision, UpdateRevision
from wiredex.projects.domain.bom import BomNotes
from wiredex.projects.domain.designators import Designators
from wiredex.projects.domain.project import ProjectDetails
from wiredex.projects.domain.revision import Revision, RevisionDetails
from wiredex.projects.domain.values import (
    Description,
    Notes,
    PartId,
    ProjectName,
    RevisionId,
    RevisionLabel,
    Summary,
    Tags,
    WorkspaceId,
)

# A factory over the workspace, like every projects use case's, so the clear scopes to the one
# bench (ADR 0007).
type UnitOfWorkFactory = Callable[[WorkspaceId], ProjectsUnitOfWork]

# The bench's sample parts by name, resolved by the composition root after the catalog's
# restore minted their ids. A part the sample catalog no longer holds is simply absent, and
# its lines are skipped: the seeding never names a part that isn't there.
type DemoParts = Callable[[WorkspaceId], Awaitable[Mapping[str, PartId]]]


@dataclass(frozen=True, slots=True)
class SampleBomLine:
    """A line of a sample BOM, as the editor's row would hold it: its part by sample name."""

    designators: str
    part: str
    quantity: int | None = None
    notes: str | None = None


@dataclass(frozen=True, slots=True)
class SampleRevision:
    """A project's first revision, in the words the edit dialog would hold, and its BOM.

    `reserved` marks the one revision a restore reserves through the reserve use case once the
    projects are back (10's requirement 12): the sample *Greenhouse controller* `A`.
    """

    label: str
    summary: str
    notes: str | None = None
    lines: tuple[SampleBomLine, ...] = ()
    reserved: bool = False


@dataclass(frozen=True, slots=True)
class SampleFork:
    """A later revision, forked from the sample revision labelled `source`, and the lines it
    adds to the ones the fork copies."""

    source: str
    label: str
    summary: str
    notes: str | None = None
    lines: tuple[SampleBomLine, ...] = ()


@dataclass(frozen=True, slots=True)
class SampleProject:
    """A sample project: its details, its first revision, and the forks that follow it."""

    name: str
    description: str
    tags: tuple[str, ...]
    first: SampleRevision
    forks: tuple[SampleFork, ...] = ()


# Small on purpose, and still enough to show what projects do: tags two projects share and one
# each keeps, a description, and a revision B forked from A with a note on why. The BOMs show
# what the shortage report is for, against the sample stock (09's requirement 10.2): the
# weather station is short its BME280, and B, which copies A's lines, its regulator and its
# two 2u2 as well; the wire is a consumable on a line without designators; the greenhouse
# fills a range, R1–R3, and is complete.
SAMPLE_PROJECTS: tuple[SampleProject, ...] = (
    SampleProject(
        "Weather station",
        "A BME280 on an ESP32, logging temperature, humidity and pressure every five minutes.",
        ("esp32", "i2c", "outdoor"),
        first=SampleRevision(
            "A",
            "breadboard",
            lines=(
                SampleBomLine("U1", "ESP32-DevKitC"),
                SampleBomLine("U2", "BME280"),
                SampleBomLine("R1, R2", "Resistor 4k7 0805", notes="I²C pull-ups"),
                SampleBomLine("C1", "Capacitor 100n 0603 X7R", notes="BME280 decoupling"),
                SampleBomLine("", "Hook-up wire 22 AWG", quantity=1, notes="about 2 m of jumpers"),
            ),
        ),
        forks=(
            SampleFork(
                "A",
                "B",
                "perfboard",
                notes=(
                    "The sensor moves off the board, on a 20 cm cable: next to the ESP32 it "
                    "read about 2 °C high from the module's own heat."
                ),
                lines=(
                    SampleBomLine("U3", "AMS1117-3.3", notes="3V3 from the battery"),
                    SampleBomLine(
                        "C2, C3", "Capacitor 2u2 0805 X5R", notes="regulator input and output"
                    ),
                ),
            ),
        ),
    ),
    SampleProject(
        "Greenhouse controller",
        "Waters the tomatoes when the soil dries out.",
        ("esp32", "relay"),
        first=SampleRevision(
            "A",
            "breadboard",
            lines=(
                SampleBomLine("U1", "ESP32-DevKitC"),
                SampleBomLine(
                    "R1-R3", "Resistor 10k 0603", notes="soil probe divider and pull-downs"
                ),
                SampleBomLine("C1", "Capacitor 100n 0603 X7R"),
            ),
            reserved=True,
        ),
    ),
)


class SampleBoms:
    """What the sample BOMs go in through: the bench's sample parts by name, and `AddBomLine`.

    Kept apart from the restore's other use cases because it is the one half that needs an
    answer from another module, which `demo_parts` carries in (09's requirement 10.2).
    """

    def __init__(self, add_bom_line: AddBomLine, demo_parts: DemoParts) -> None:
        self._add_bom_line = add_bom_line
        self._demo_parts = demo_parts

    async def parts(self, workspace_id: WorkspaceId) -> Mapping[str, PartId]:
        """The bench's sample parts by name, read once the catalog's restore has run."""
        return await self._demo_parts(workspace_id)

    async def add(
        self,
        workspace_id: WorkspaceId,
        revision: Revision,
        lines: tuple[SampleBomLine, ...],
        parts: Mapping[str, PartId],
    ) -> None:
        """The sample lines, in order, skipping any whose part the sample catalog lacks."""
        for line in lines:
            part_id = parts.get(line.part)
            if part_id is None:
                continue
            await self._add_bom_line(
                workspace_id,
                revision.id,
                NewBomLine(
                    part_id,
                    Designators.parse(line.designators),
                    line.quantity,
                    None if line.notes is None else BomNotes(line.notes),
                ),
            )


@dataclass(frozen=True, slots=True)
class SampleWrites:
    """The three use cases the samples are written through, bundled into one argument.

    `RestoreSampleProjects` also needs the BOMs and the reserve, and six constructor arguments
    break ruff's `max-args = 5`, which nothing in the codebase suppresses (as 09's `SampleBoms`
    already found). These three belong together anyway: a project, its first revision's edit,
    and the forks that follow, all written as the web writes them.
    """

    create_project: CreateProject
    update_revision: UpdateRevision
    fork_revision: ForkRevision


class RestoreSampleProjects:
    """Puts one demo bench's sample projects back, whatever the guest did to them.

    Part of the nightly `wiredex demo reset` and of `wiredex demo invite` (ADR 0011, decision
    16). Which workspaces are demo benches is identity's to answer, so the composition root
    asks there and hands the ids here: projects imports no other module.
    """

    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        writes: SampleWrites,
        boms: SampleBoms,
        reserve_revision: ReserveRevision,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._create_project = writes.create_project
        self._update_revision = writes.update_revision
        self._fork_revision = writes.fork_revision
        self._boms = boms
        self._reserve_revision = reserve_revision

    async def __call__(self, workspace_id: WorkspaceId) -> int:
        """Restores the bench's sample projects and returns how many it ended with.

        The clear is one transaction; each project, edit, fork and line then goes in through
        its own use case, each its own transaction, as the web writes them. Once every project
        and its BOM are back, the sample *Greenhouse controller* `A` is reserved through the
        reserve use case, its own unit of work, with no named units, so the automatic choice
        sets the bench's board and the other parts aside (requirement 12). The workspace it is
        opened for is the only one any step can touch (ADR 0007).
        """
        await self._clear(workspace_id)
        parts = await self._boms.parts(workspace_id)
        to_reserve: list[RevisionId] = []
        for sample in SAMPLE_PROJECTS:
            to_reserve += await self._write(workspace_id, sample, parts)
        for revision_id in to_reserve:
            await self._reserve_revision(workspace_id, revision_id, [])
        return len(SAMPLE_PROJECTS)

    async def _clear(self, workspace_id: WorkspaceId) -> None:
        async with self._unit_of_work(workspace_id) as work:
            await work.clear()
            await work.commit()

    async def _write(
        self, workspace_id: WorkspaceId, sample: SampleProject, parts: Mapping[str, PartId]
    ) -> list[RevisionId]:
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
        # Each revision's own lines before anything is forked from it, so a fork copies them.
        await self._boms.add(workspace_id, first, sample.first.lines, parts)
        by_label: dict[str, Revision] = {first.label.value: first}
        reserved = [first.id] if sample.first.reserved else []
        for fork in sample.forks:
            forked = await self._fork_revision(
                workspace_id,
                by_label[fork.source].id,
                NewRevision(RevisionLabel(fork.label), Summary(fork.summary), _notes(fork.notes)),
            )
            await self._boms.add(workspace_id, forked, fork.lines, parts)
            by_label[fork.label] = forked
        return reserved


def _notes(text: str | None) -> Notes | None:
    return None if text is None else Notes(text)
