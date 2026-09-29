"""What the projects use cases need from the outside, as Protocols over domain types.

No repository method takes a workspace: the unit of work is built for one workspace and its
repositories only ever see that workspace's rows (ADR 0007). The unit of work exposes them as
read-only properties, because a protocol attribute would have to match exactly, so
`SqlProjects` wouldn't count as `Projects`.

The commands and views live here too, next to the ports they travel through, as inventory's
do.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from wiredex.projects.domain.bom import BillOfMaterials, BomLine, BomNotes, LineContent
from wiredex.projects.domain.designators import Designators
from wiredex.projects.domain.filter import ProjectFilter
from wiredex.projects.domain.lifecycle import Transition
from wiredex.projects.domain.project import Project
from wiredex.projects.domain.project_revisions import ProjectRevisions
from wiredex.projects.domain.reservation import ReservableStock, Reservation
from wiredex.projects.domain.revision import Revision, RevisionDetails
from wiredex.projects.domain.shortage import PartFacts, ShortageReport
from wiredex.projects.domain.values import (
    LocationId,
    Notes,
    PartId,
    ProjectId,
    ProjectName,
    RevisionId,
    RevisionLabel,
    RevisionStatus,
    Summary,
    Tag,
    UnitId,
    WorkspaceId,
)
from wiredex.shared_kernel.application.ports import UnitOfWork


@dataclass(frozen=True, slots=True)
class RevisionRef:
    """A revision found by its id alone: enough to name it and link to its project (10.2)."""

    revision_id: RevisionId
    label: RevisionLabel
    summary: Summary | None
    status: RevisionStatus
    project_id: ProjectId
    project_name: ProjectName


class Projects(Protocol):
    async def add(self, project: Project) -> None: ...

    async def get(self, project_id: ProjectId) -> Project | None: ...

    async def locked(self, project_id: ProjectId) -> Project | None:
        """The project, its row locked until the transaction ends (decision 15).

        Every change to a project's revisions takes this first, so two requests reading the
        siblings to choose a label or to count what is left take turns.
        """
        ...

    async def named(self, name: ProjectName) -> Project | None:
        """The project holding the name, compared folded as the unique index folds it."""
        ...

    async def matching(self, wanted: ProjectFilter) -> list[Project]:
        """The projects `wanted.matches`, in no particular order: the list orders them by
        last activity, which needs their revisions."""
        ...

    async def tag_counts(self) -> list[TagCount]:
        """Each tag the workspace's projects carry, with how many carry it, alphabetical."""
        ...

    async def remove(self, project: Project) -> None:
        """The project and, by the database's cascade and the fakes' own, its revisions."""
        ...


class Revisions(Protocol):
    async def add(self, revision: Revision) -> None:
        """Flushed at once, so content copied with Core in the same transaction finds it."""
        ...

    async def get(self, revision_id: RevisionId) -> Revision | None: ...

    async def project_of(self, revision_id: RevisionId) -> ProjectId | None:
        """The revision's project id alone, no entity (decision 12): what `lock_revision`
        locks before it reads the revision itself."""
        ...

    async def of_project(self, project_id: ProjectId) -> ProjectRevisions: ...

    async def of_projects(
        self, project_ids: Sequence[ProjectId]
    ) -> Mapping[ProjectId, ProjectRevisions]:
        """Every listed project's revisions in one read, for the list (decision 11).

        A project with no revision left may be missing from the mapping: one deleted between
        the list's two reads.
        """
        ...

    async def remove(self, revision: Revision) -> None:
        """The revision; a revision forked from it keeps going, its `forked_from` cleared."""
        ...

    async def ref(self, revision_id: RevisionId) -> RevisionRef | None:
        """The revision named by its id alone, joined to its project, or None (10.2).

        Another workspace's id is simply not found, as `get` is (requirement 11.3).
        """
        ...

    async def refs(self, revision_ids: Sequence[RevisionId]) -> Mapping[RevisionId, RevisionRef]:
        """The refs of the listed revisions in one read, for the part-holdings list (10.4).

        A revision missing from the workspace is absent from the mapping.
        """
        ...


class RevisionContent(Protocol):
    """One kind of thing a revision holds, as a fork copies it (decision 6).

    Bound to the fork's transaction by whoever builds the unit of work; never commits. 09's BOM
    lines and 11's nets implement it inside `projects`; content another module keeps arrives
    through a unit of work bootstrap extends.
    """

    async def copy(self, source: Revision, target: Revision) -> None: ...


class ProjectsUnitOfWork(UnitOfWork, Protocol):
    async def clear(self) -> None:
        """Every project and revision of the workspace, for a demo bench being restored."""
        ...

    @property
    def projects(self) -> Projects: ...

    @property
    def revisions(self) -> Revisions: ...

    @property
    def revision_contents(self) -> Sequence[RevisionContent]:
        """What a fork copies, in order. Empty in this spec."""
        ...


class BomLines(Protocol):
    """A revision's lines and their designators, written with Core as a pinout is."""

    async def of_revision(self, revision_id: RevisionId) -> BillOfMaterials:
        """The lines oldest first with their designators, in two reads (12.3)."""
        ...

    async def add(self, line: BomLine) -> None: ...

    async def add_all(self, lines: Sequence[BomLine]) -> None:
        """Many lines at once, for a fork's copy: two statements whatever their number."""
        ...

    async def update(self, before: BomLine, after: BomLine) -> None:
        """The part, quantity and notes, and the designators by difference (decision 8)."""
        ...

    async def remove(self, line: BomLine) -> None:
        """The line and, by the database's cascade and the fakes' own, its designators."""
        ...

    async def uses_of(self, part_id: PartId, limit: int) -> BomUses:
        """The revisions whose BOM names the part: the first `limit`, by project name and
        then oldest revision first, and how many there are in all."""
        ...


class BomUnitOfWork(ProjectsUnitOfWork, Protocol):
    """A projects unit of work that also holds BOM lines.

    A port of its own rather than a member of `ProjectsUnitOfWork`, as 07's
    `IntakeUnitOfWork` extends inventory's: 08's use cases and whatever bootstrap wires them
    with keep their port, and only the BOM's use cases ask for this one.
    """

    @property
    def bom_lines(self) -> BomLines: ...


# --- The build lifecycle: the stock a transition touches, in projects' terms (decision 8) ---


@dataclass(frozen=True, slots=True)
class HeldLot:
    """One lot a revision reserves: what it holds there and where (decision 8)."""

    part_id: PartId
    location_id: LocationId
    location_code: str
    quantity: int


@dataclass(frozen=True, slots=True)
class Holdings:
    """`HeldStock` in projects' terms: per lot what the revision reserves, per part what its
    build consumed and hasn't returned (requirements 8.5, 8.6)."""

    reserved: tuple[HeldLot, ...]
    consumed: Mapping[PartId, int]


@dataclass(frozen=True, slots=True)
class RevisionHolding:
    """How much of one part a revision holds: reserved, or consumed by its build (10.4)."""

    revision_id: RevisionId
    reserved: int
    consumed: int


@dataclass(frozen=True, slots=True)
class HeldUnit:
    """One unit a revision holds. No status: a reserved revision's are all reserved and a
    built one's all built (requirement 3.6), so the revision's status says it."""

    unit_id: UnitId
    code: str
    part_id: PartId
    location_code: str | None  # None while built: a unit in use sits on a board, not in a drawer


class BuildStock(Protocol):
    """Inventory's stock as a transition sees it, on the transition's session (decision 8).

    Bound by bootstrap to the session projects' unit of work opened, under the workspace
    setting that unit of work applied, so row-level security scopes every read and write of a
    transition (requirement 11.1). It never commits; the projects unit of work does.
    """

    async def available(
        self, part_ids: Collection[PartId], named: Collection[UnitId]
    ) -> ReservableStock:
        """Lock the parts' in-stock units and the named ones, then their lots (decision 10)."""
        ...

    async def reserve(self, revision_id: RevisionId, reservation: Reservation) -> None:
        """Write the choice against what `available` locked in this transaction (2.4 to 2.6)."""
        ...

    async def release(self, revision_id: RevisionId) -> datetime:
        """One `RELEASE` per lot of the whole reservation; the time it stamped (4.1)."""
        ...

    async def consume(self, revision_id: RevisionId) -> datetime:
        """One `CONSUME` per lot of the whole reservation; the time it stamped (5.1)."""
        ...

    async def return_to(self, revision_id: RevisionId, location_id: LocationId) -> datetime:
        """One `RETURN` per consumed part at the location; the time it stamped (6.2)."""
        ...

    async def holdings(self, revision_id: RevisionId) -> Holdings:
        """What the revision holds, folded from its movements, in one query (8.5, 10.6)."""
        ...

    async def holdings_of_part(self, part_id: PartId) -> list[RevisionHolding]:
        """Each revision holding some of the part, folded the same way (requirement 10.4)."""
        ...

    async def units_of(self, revision_id: RevisionId) -> list[HeldUnit]:
        """The units reserved for or built into the revision, in one query (3.11)."""
        ...


class BuildParts(Protocol):
    """The catalog's part facts on the transition's session (decision 8)."""

    async def describe(self, part_ids: Collection[PartId]) -> Mapping[PartId, PartFacts]:
        """09's facts and resolved flags; a part it doesn't find is absent, so unknown."""
        ...


class BuildUnitOfWork(BomUnitOfWork, Protocol):
    """A projects unit of work that also exposes inventory's stock and catalog's parts, both
    on its own session (decision 8): a transition is one transaction across three modules.

    A port of its own, as `BomUnitOfWork` extends `ProjectsUnitOfWork`: only the transitions
    and the lifecycle reads ask for it, and bootstrap binds `stock` and `parts`.
    """

    @property
    def stock(self) -> BuildStock: ...

    @property
    def parts(self) -> BuildParts: ...


class PartLookup(Protocol):
    """What the catalog holds about some parts, answered by bootstrap over catalog's
    `DescribeParts` (decision 1)."""

    async def describe(
        self, workspace_id: WorkspaceId, part_ids: Sequence[PartId]
    ) -> Mapping[PartId, PartFacts]:
        """The parts the workspace's catalog holds among these; a part it doesn't is absent."""
        ...


class StockLevels(Protocol):
    """How many of some parts are available, answered by bootstrap over inventory's
    `AvailableStock`."""

    async def available(
        self, workspace_id: WorkspaceId, part_ids: Sequence[PartId]
    ) -> Mapping[PartId, int]:
        """Each part's available stock over its lots; a part no lot holds is absent."""
        ...


# --- Commands and views: the shapes the use cases take in and hand back --------------------


@dataclass(frozen=True, slots=True)
class NewRevision:
    """A revision to add or fork: no label means the suggested one (decision 4)."""

    label: RevisionLabel | None = None
    summary: Summary | None = None
    notes: Notes | None = None

    def details_with(self, label: RevisionLabel) -> RevisionDetails:
        """The details the revision is created with, once its project's revisions settled
        the label."""
        return RevisionDetails(label, self.summary, self.notes)


@dataclass(frozen=True, slots=True)
class ProjectView:
    """A project page: the project and its revisions, oldest first. The latest and the label
    a new revision would take are read off them (requirement 1.6)."""

    project: Project
    revisions: ProjectRevisions


@dataclass(frozen=True, slots=True)
class ProjectSummary:
    """A row of the project list (requirement 3.1)."""

    project: Project
    latest: Revision
    revision_count: int
    last_activity: datetime  # decision 11


@dataclass(frozen=True, slots=True)
class TagCount:
    """A tag of the workspace and how many of its projects carry it (requirement 2.6)."""

    tag: Tag
    projects: int


@dataclass(frozen=True, slots=True)
class NewBomLine:
    """A line as the API read it: values typed, the quantity rule not yet applied. Adding
    and editing both take one, since an edit replaces all four (requirement 4.9)."""

    part_id: PartId
    designators: Designators = field(default_factory=Designators.none)
    quantity: int | None = None
    notes: BomNotes | None = None

    def content(self) -> LineContent:
        return LineContent.of(self.part_id, self.designators, self.quantity, self.notes)


@dataclass(frozen=True, slots=True)
class BomView:
    """A revision's BOM as the page shows it: its lines and their report (requirement 6.1)."""

    revision: Revision
    bom: BillOfMaterials
    report: ShortageReport

    @property
    def editable(self) -> bool:
        """Only a draft's BOM changes (requirement 5.2)."""
        return self.revision.status is RevisionStatus.DRAFT


@dataclass(frozen=True, slots=True)
class BomUse:
    """A revision whose BOM names a part, as catalog's deletion refusal names it."""

    project_id: ProjectId
    project_name: ProjectName
    revision_id: RevisionId
    revision_label: RevisionLabel


@dataclass(frozen=True, slots=True)
class BomUses:
    """The first few revisions naming a part, and how many there are in all."""

    uses: tuple[BomUse, ...]
    total: int


@dataclass(frozen=True, slots=True)
class HeldPart:
    """One part a reserved or built revision holds: what it reserves, per location, or what
    its build consumed, and its units (requirement 10.1)."""

    part_id: PartId
    facts: PartFacts | None  # None for a part the catalog no longer holds (09's unknown)
    reserved: tuple[HeldLot, ...]  # by location code
    consumed: int
    units: tuple[HeldUnit, ...]  # in code order


@dataclass(frozen=True, slots=True)
class Lifecycle:
    """A revision's build: its status, the transitions it allows, whether it can be deleted,
    and each part it holds (requirement 10.1)."""

    status: RevisionStatus
    transitions: tuple[Transition, ...]  # transitions_from(status)
    deletable: bool  # status.deletable and the project has other revisions (9.2)
    parts: tuple[HeldPart, ...]  # by part name


@dataclass(frozen=True, slots=True)
class PartHoldingView:
    """One revision holding a part, with its ref (requirement 10.4)."""

    revision: RevisionRef
    reserved: int
    consumed: int
