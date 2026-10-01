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
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Self
from uuid import uuid7

from support.identity import ManualClock, NewIds
from wiredex.projects.api.router import ProjectsUseCases
from wiredex.projects.application.bom import (
    AddBomLine,
    CopyBomLines,
    GetBom,
    ListPartUses,
    RemoveBomLine,
    UpdateBomLine,
)
from wiredex.projects.application.lifecycle import (
    BuildRevision,
    CancelReservation,
    DismantleRevision,
    GetLifecycle,
    GetRevisionRef,
    ListPartHoldings,
    ReserveRevision,
)
from wiredex.projects.application.netlist import (
    AddNet,
    CopyNetlist,
    GetNetlist,
    GetPinUsage,
    RemoveNet,
    UpdateNet,
)
from wiredex.projects.application.ports import (
    BomUse,
    BomUses,
    HeldLot,
    HeldUnit,
    Holdings,
    RevisionContent,
    RevisionHolding,
    RevisionRef,
    TagCount,
)
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
from wiredex.projects.domain.netlist import Net, Netlist, PinReference
from wiredex.projects.domain.pin_usage import PinUse
from wiredex.projects.domain.pins import PartPins
from wiredex.projects.domain.project import Project
from wiredex.projects.domain.project_revisions import ProjectRevisions
from wiredex.projects.domain.reservation import (
    ReservableLot,
    ReservableStock,
    Reservation,
    StockUnit,
)
from wiredex.projects.domain.revision import Revision
from wiredex.projects.domain.shortage import PartFacts
from wiredex.projects.domain.values import (
    BomLineId,
    Description,
    LocationId,
    LotId,
    NetId,
    PartId,
    ProjectId,
    ProjectName,
    RevisionId,
    RevisionLabel,
    RevisionStatus,
    Tags,
    UnitId,
    WorkspaceId,
)
from wiredex.shared_kernel.application.ports import IdGenerator
from wiredex.shared_kernel.domain.trash import TrashPosition

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
                in_trash=self._projects[revision.project_id].in_trash,
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


class InMemoryNets:
    """One workspace's nets, read back in the order `SqlNets` reads them.

    `uses_of_part` names projects and revisions and reads the BOM, as the SQL joins them, so
    the unit of work hands it the other stores' rows, as it does `InMemoryBomLines`.
    """

    def __init__(
        self,
        projects: Mapping[ProjectId, Project],
        revisions: Mapping[RevisionId, Revision],
        lines: Mapping[BomLineId, BomLine],
    ) -> None:
        self.saved: dict[NetId, Net] = {}
        self.reads = 0
        self._projects = projects
        self._revisions = revisions
        self._lines = lines

    async def of_revision(self, revision_id: RevisionId) -> Netlist:
        self.reads += 1
        return Netlist(revision_id, tuple(self._of(revision_id)))

    async def add(self, net: Net) -> None:
        self.saved[net.id] = net

    async def add_all(self, nets: Sequence[Net]) -> None:
        for net in nets:
            self.saved[net.id] = net

    async def update(self, before: Net, after: Net) -> None:
        assert before.id == after.id
        self.saved[after.id] = after

    async def remove(self, net: Net) -> None:
        del self.saved[net.id]

    async def uses_of_part(self, part_id: PartId) -> list[PinUse]:
        self.reads += 1
        holding = {
            (line.revision_id, designator)
            for line in self._lines.values()
            if line.content.part_id == part_id
            for designator in line.content.designators
        }
        found = [
            (net, reference)
            for net in self.saved.values()
            for reference in net.content.pins
            if (net.revision_id, reference.designator) in holding
            and not self._projects[self._revisions[net.revision_id].project_id].in_trash
        ]

        def order(entry: tuple[Net, PinReference]) -> tuple[object, ...]:
            net, reference = entry
            revision = self._revisions[net.revision_id]
            project = self._projects[revision.project_id]
            return (
                project.name.fold(),
                revision.created_at,
                revision.id,
                reference.designator,
                reference.pin.sort_key(),
                net.created_at,
                net.id,
            )

        return [
            _use_of(self._projects, self._revisions[net.revision_id], net, reference)
            for net, reference in sorted(found, key=order)
        ]

    def take_revision(self, revision_id: RevisionId) -> None:
        """The cascade from a deleted revision."""
        for net in self._of(revision_id):
            del self.saved[net.id]

    def _of(self, revision_id: RevisionId) -> list[Net]:
        nets = [net for net in self.saved.values() if net.revision_id == revision_id]
        return sorted(nets, key=lambda net: (net.created_at, net.id))


def _use_of(
    projects: Mapping[ProjectId, Project], revision: Revision, net: Net, reference: PinReference
) -> PinUse:
    return PinUse(
        revision.project_id,
        projects[revision.project_id].name,
        revision.id,
        revision.label,
        revision.status,
        reference.designator,
        reference.pin,
        net.id,
        net.content.name,
        net.content.color,
    )


class InMemoryNetlistPins:
    """Catalog's pinouts over a dict; a part with no pins is absent, as `of_parts` leaves it."""

    def __init__(self) -> None:
        self.pinouts: dict[PartId, PartPins] = {}
        self.asked: list[tuple[PartId, ...]] = []

    async def of_parts(self, part_ids: Collection[PartId]) -> Mapping[PartId, PartPins]:
        self.asked.append(tuple(part_ids))
        return {part_id: self.pinouts[part_id] for part_id in part_ids if part_id in self.pinouts}


class InMemoryRevisions:
    def __init__(self) -> None:
        self.saved: dict[RevisionId, Revision] = {}
        self.reads = 0
        # A shared view of the workspace's projects, so `ref` and `refs` can name them; the
        # unit of work sets it to the same dict the projects store keeps.
        self._projects: Mapping[ProjectId, Project] = {}
        self.lines = InMemoryBomLines({}, self.saved)
        self.nets = InMemoryNets({}, self.saved, {})

    async def add(self, revision: Revision) -> None:
        self.saved[revision.id] = revision

    async def get(self, revision_id: RevisionId) -> Revision | None:
        self.reads += 1
        return self._live(revision_id)

    async def project_of(self, revision_id: RevisionId) -> ProjectId | None:
        self.reads += 1
        revision = self._live(revision_id)
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
        self.nets.take_revision(revision.id)
        for other in self.saved.values():
            if other.forked_from == revision.id:
                other.forked_from = None

    async def ref(self, revision_id: RevisionId) -> RevisionRef | None:
        self.reads += 1
        revision = self._live(revision_id)
        return None if revision is None else self._ref_of(revision)

    async def refs(self, revision_ids: Sequence[RevisionId]) -> Mapping[RevisionId, RevisionRef]:
        self.reads += 1
        found: dict[RevisionId, RevisionRef] = {}
        for revision_id in revision_ids:
            revision = self._live(revision_id)
            if revision is not None:
                found[revision_id] = self._ref_of(revision)
        return found

    def _live(self, revision_id: RevisionId) -> Revision | None:
        """The revision, unless its project is gone or in the trash, where a revision is with
        it (16-soft-delete-and-trash, decision 2)."""
        revision = self.saved.get(revision_id)
        if revision is None:
            return None
        project = self._projects.get(revision.project_id)
        return None if project is None or project.in_trash else revision

    def _ref_of(self, revision: Revision) -> RevisionRef:
        project = self._projects[revision.project_id]
        return RevisionRef(
            revision_id=revision.id,
            label=revision.label,
            summary=revision.summary,
            status=revision.status,
            project_id=revision.project_id,
            project_name=project.name,
        )

    def take_project(self, project_id: ProjectId) -> None:
        """The cascade from a deleted project, and from its revisions to their lines."""
        for revision in [r for r in self.saved.values() if r.project_id == project_id]:
            del self.saved[revision.id]
            self.lines.take_revision(revision.id)
            self.nets.take_revision(revision.id)

    def _of(self, project_id: ProjectId) -> ProjectRevisions:
        project = self._projects.get(project_id)
        if project is not None and project.in_trash:
            return ProjectRevisions(())
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
        return self._live().get(project_id)

    async def locked(self, project_id: ProjectId) -> Project | None:
        self.reads += 1
        project = self._live().get(project_id)
        if project is not None:
            self.locks.append(project_id)
        return project

    async def named(self, name: ProjectName) -> Project | None:
        self.reads += 1
        holders = (p for p in self.saved.values() if p.name.fold() == name.fold())
        return next(holders, None)

    async def matching(self, wanted: ProjectFilter) -> list[Project]:
        self.reads += 1
        return [project for project in self._live().values() if wanted.matches(project)]

    async def tag_counts(self) -> list[TagCount]:
        self.reads += 1
        counts = Counter(tag for project in self._live().values() for tag in project.tags.values)
        return [TagCount(tag, counts[tag]) for tag in sorted(counts, key=lambda tag: tag.value)]

    async def remove(self, project: Project) -> None:
        del self.saved[project.id]
        self._revisions.take_project(project.id)

    async def trashed(self, before: TrashPosition | None, limit: int) -> list[Project]:
        held = [p for p in self._trash() if before is None or _position(p) < before]
        return sorted(held, key=_position, reverse=True)[:limit]

    async def in_trash(self, project_id: ProjectId) -> Project | None:
        found = self.saved.get(project_id)
        return found if found is not None and found.in_trash else None

    async def empty_trash(self) -> int:
        trashed = self._trash()
        for project in trashed:
            await self.remove(project)
        return len(trashed)

    def _live(self) -> dict[ProjectId, Project]:
        return {key: project for key, project in self.saved.items() if not project.in_trash}

    def _trash(self) -> list[Project]:
        return [project for project in self.saved.values() if project.in_trash]


def _position(project: Project) -> TrashPosition:
    assert project.trashed_at is not None  # only a project in the trash has a position in it
    return TrashPosition(project.trashed_at, project.id)


class InMemoryProjectsUnitOfWork:
    """A unit of work over shared in-memory stores; counts commits and reads, and records who
    it was opened for.

    The repositories are plain attributes, which satisfy the read-only properties the
    `ProjectsUnitOfWork` and `BomUnitOfWork` protocols declare. `revision_contents` starts
    with the BOM's copy and is settable, so 08's fork tests register their own contents
    instead, and 09's register theirs after the copy.
    """

    def __init__(self, ids: IdGenerator) -> None:
        self.revisions = InMemoryRevisions()
        self.projects = InMemoryProjects(self.revisions)
        self.bom_lines = InMemoryBomLines(self.projects.saved, self.revisions.saved)
        # The revisions' cascade reaches the same lines the unit of work hands out, and its
        # `ref`/`refs` name the same projects the store keeps.
        self.revisions.lines = self.bom_lines
        self.nets = InMemoryNets(self.projects.saved, self.revisions.saved, self.bom_lines.saved)
        self.revisions.nets = self.nets
        self.pins = InMemoryNetlistPins()
        self.revisions._projects = self.projects.saved
        # Inventory's stock and catalog's parts on this unit of work's "session": a transition
        # writes all three in one commit (decision 8). Both never commit; this unit of work does.
        self.stock = InMemoryBuildStock()
        self.parts = InMemoryBuildParts()
        # The BOM first, as `SqlProjectsUnitOfWork` registers it (decision 15).
        self.revision_contents: Sequence[RevisionContent] = (
            CopyBomLines(self.bom_lines, ids),
            CopyNetlist(self.nets, ids),
        )
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
        # Only this bench's projects, revisions and BOM lines, as the real
        # `SqlProjectsUnitOfWork.clear` does: inventory has its own clear, run before this in
        # a reset, so the stock a transition reads is left alone here.
        self.projects.saved.clear()
        self.revisions.saved.clear()
        self.bom_lines.saved.clear()
        self.nets.saved.clear()


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


class UnknownLocationInFakeError(RuntimeError):
    """`InMemoryBuildStock.return_to` given a location the fake doesn't hold, which the real
    `InventoryBuildStock` turns into an `UnknownLocationError`. Tests drive that mapping in the
    bootstrap suite (task 12); here the fake raises before any write, as the adapter would."""


@dataclass
class _Lot:
    """One lot the fake stock holds: a part in a location, with its counts and its units."""

    lot_id: LotId
    part_id: PartId
    location_id: LocationId
    location_code: str
    on_hand: int
    reserved: int = 0

    @property
    def available(self) -> int:
        return self.on_hand - self.reserved


@dataclass
class _Unit:
    """One tracked unit: its lot and status, and the revision it is held for, if any."""

    unit_id: UnitId
    code: str
    part_id: PartId
    lot_id: LotId
    status: str = "in_stock"  # in_stock, reserved, in_use, retired
    revision_id: RevisionId | None = None

    @property
    def in_stock(self) -> bool:
        return self.status == "in_stock"


class InMemoryBuildStock:
    """Inventory's `BuildStock` in memory: lots, units and a per-revision record of what each
    reserve took, so `holdings`, `holdings_of_part` and `units_of` fold back the same way the
    real ledger does. It never commits; the unit of work does.

    The fake keeps the invariant the design states (decision 5): a reserve raises a lot's
    reserved and marks its chosen units reserved; a release lowers reserved and puts the units
    back; a build lowers on hand and reserved and marks the units in use; a return raises on
    hand at the chosen location and puts the units in stock there. Every write stamps `now`
    from a clock that moves each call, so the transitions' times are ordered as the ledger's
    are.
    """

    def __init__(self, clock: ManualClock | None = None) -> None:
        self._clock = clock or ManualClock(NOW)
        self.lots: dict[LotId, _Lot] = {}
        self.units: dict[UnitId, _Unit] = {}
        # Per revision, the picks it holds: lot -> quantity reserved there (cancel/build read it).
        self._reserved: dict[RevisionId, dict[LotId, int]] = {}
        # Per revision, what its build consumed and hasn't returned: part -> quantity.
        self._consumed: dict[RevisionId, dict[PartId, int]] = {}
        # `changed` the next `available` reports, so a test can drive the stock_changed path.
        self.next_changed = False

    # --- seeding, for tests -----------------------------------------------------------------

    def hold_lot(
        self,
        part_id: PartId,
        *,
        location_id: LocationId,
        location_code: str,
        on_hand: int,
        units: Sequence[str] = (),
    ) -> _Lot:
        """A lot with `on_hand` pieces, `units` of them tracked (one per code), in stock."""
        lot = _Lot(LotId(uuid7()), part_id, location_id, location_code, on_hand)
        self.lots[lot.lot_id] = lot
        for code in units:
            unit = _Unit(UnitId(uuid7()), code, part_id, lot.lot_id)
            self.units[unit.unit_id] = unit
        return lot

    def unit(self, code: str) -> _Unit:
        return next(unit for unit in self.units.values() if unit.code == code)

    def clear(self) -> None:
        self.lots.clear()
        self.units.clear()
        self._reserved.clear()
        self._consumed.clear()

    # --- the port ---------------------------------------------------------------------------

    async def available(
        self, part_ids: Collection[PartId], named: Collection[UnitId]
    ) -> ReservableStock:
        wanted = set(part_ids)
        lots = tuple(
            sorted(
                (
                    ReservableLot(lot.lot_id, lot.part_id, lot.location_code, lot.available)
                    for lot in self.lots.values()
                    if lot.part_id in wanted
                ),
                key=lambda lot: lot.lot_id,
            )
        )
        units = tuple(
            sorted(
                (
                    self._stock_unit(unit)
                    for unit in self.units.values()
                    if unit.part_id in wanted and unit.in_stock
                ),
                key=lambda unit: unit.unit_id,
            )
        )
        named_units = {
            unit_id: self._stock_unit(self.units[unit_id])
            for unit_id in named
            if unit_id in self.units
        }
        changed, self.next_changed = self.next_changed, False
        return ReservableStock(
            lots=lots, units=units, named=named_units, now=self._stamp(), changed=changed
        )

    async def reserve(self, revision_id: RevisionId, reservation: Reservation) -> None:
        held: dict[LotId, int] = {}
        for pick in reservation.picks:
            lot = self.lots[pick.lot_id]
            lot.reserved += pick.quantity
            held[pick.lot_id] = held.get(pick.lot_id, 0) + pick.quantity
            for unit_id in pick.unit_ids:
                unit = self.units[unit_id]
                unit.status = "reserved"
                unit.revision_id = revision_id
        self._reserved[revision_id] = held

    async def release(self, revision_id: RevisionId) -> datetime:
        for lot_id, quantity in self._reserved.pop(revision_id, {}).items():
            self.lots[lot_id].reserved -= quantity
        for unit in self._units_of(revision_id):
            unit.status = "in_stock"
            unit.revision_id = None
        return self._stamp()

    async def consume(self, revision_id: RevisionId) -> datetime:
        consumed: dict[PartId, int] = {}
        for lot_id, quantity in self._reserved.pop(revision_id, {}).items():
            lot = self.lots[lot_id]
            lot.on_hand -= quantity
            lot.reserved -= quantity
            consumed[lot.part_id] = consumed.get(lot.part_id, 0) + quantity
        for unit in self._units_of(revision_id):
            unit.status = "in_use"  # link kept
        self._consumed[revision_id] = consumed
        return self._stamp()

    async def return_to(self, revision_id: RevisionId, location_id: LocationId) -> datetime:
        if not any(lot.location_id == location_id for lot in self.lots.values()):
            raise UnknownLocationInFakeError(f"no location {location_id} in this workspace")
        consumed = self._consumed.pop(revision_id, {})
        for part_id, quantity in consumed.items():
            lot = self._lot_at(part_id, location_id)
            lot.on_hand += quantity
        for unit in self._units_of(revision_id):
            lot = self._lot_at(unit.part_id, location_id)
            unit.status = "in_stock"
            unit.lot_id = lot.lot_id
            unit.revision_id = None
        return self._stamp()

    async def holdings(self, revision_id: RevisionId) -> Holdings:
        reserved = tuple(
            HeldLot(
                self.lots[lot_id].part_id,
                self.lots[lot_id].location_id,
                self.lots[lot_id].location_code,
                quantity,
            )
            for lot_id, quantity in sorted(self._reserved.get(revision_id, {}).items())
        )
        return Holdings(reserved=reserved, consumed=dict(self._consumed.get(revision_id, {})))

    async def holdings_of_part(self, part_id: PartId) -> list[RevisionHolding]:
        revisions = set(self._reserved) | set(self._consumed)
        holdings: list[RevisionHolding] = []
        for revision_id in revisions:
            reserved = sum(
                quantity
                for lot_id, quantity in self._reserved.get(revision_id, {}).items()
                if self.lots[lot_id].part_id == part_id
            )
            consumed = self._consumed.get(revision_id, {}).get(part_id, 0)
            if reserved or consumed:
                holdings.append(RevisionHolding(revision_id, reserved, consumed))
        return holdings

    async def units_of(self, revision_id: RevisionId) -> list[HeldUnit]:
        return [
            HeldUnit(
                unit.unit_id,
                unit.code,
                unit.part_id,
                None if unit.status == "in_use" else self.lots[unit.lot_id].location_code,
            )
            for unit in sorted(self._units_of(revision_id), key=lambda unit: unit.code)
        ]

    def _stock_unit(self, unit: _Unit) -> StockUnit:
        return StockUnit(unit.unit_id, unit.code, unit.part_id, unit.lot_id, unit.in_stock)

    def _units_of(self, revision_id: RevisionId) -> list[_Unit]:
        return [unit for unit in self.units.values() if unit.revision_id == revision_id]

    def _lot_at(self, part_id: PartId, location_id: LocationId) -> _Lot:
        for lot in self.lots.values():
            if lot.part_id == part_id and lot.location_id == location_id:
                return lot
        # A return into a location that holds no lot of the part creates one, as the real
        # `return_to` inserts the missing lot (decision 4).
        lot = _Lot(LotId(uuid7()), part_id, location_id, f"WX-L-{len(self.lots) + 1:04d}", 0)
        self.lots[lot.lot_id] = lot
        return lot

    def _stamp(self) -> datetime:
        now = self._clock.now()
        self._clock.advance(timedelta(seconds=1))
        return now


class InMemoryBuildParts:
    """Catalog's `BuildParts` over a dict of facts; counts what it was asked."""

    def __init__(self) -> None:
        self.facts: dict[PartId, PartFacts] = {}
        self.asked: list[tuple[PartId, ...]] = []

    async def describe(self, part_ids: Collection[PartId]) -> Mapping[PartId, PartFacts]:
        self.asked.append(tuple(part_ids))
        return {part_id: self.facts[part_id] for part_id in part_ids if part_id in self.facts}

    def hold(self, name: str, *, tracked: bool = False, not_stocked: bool = False) -> PartId:
        part_id = PartId(uuid7())
        self.facts[part_id] = PartFacts(part_id, name, None, None, None, tracked, not_stocked)
        return part_id


class World:
    """The projects fakes over an empty bench, and the use cases built on them.

    Seeds are written straight to the stores, not through use cases: a test of one use case
    shouldn't depend on another one working, and a revision in a status other than draft can't
    be made through the use cases before 10-build-lifecycle.
    """

    def __init__(self) -> None:
        self.clock = ManualClock(NOW)
        self.ids = NewIds()
        self.work = InMemoryProjectsUnitOfWork(self.ids)
        factory = self.work.for_workspace
        self.create_project = CreateProject(factory, self.clock, self.ids)
        self.update_project = UpdateProject(factory, self.clock)
        self.delete_project = DeleteProject(factory, self.clock)
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
        # The build lifecycle over the unit of work's own stock and parts (decision 8).
        self.build_stock = self.work.stock
        self.build_parts = self.work.parts
        self.reserve_revision = ReserveRevision(factory)
        self.cancel_reservation = CancelReservation(factory)
        self.build_revision = BuildRevision(factory)
        self.dismantle_revision = DismantleRevision(factory)
        self.get_lifecycle = GetLifecycle(factory)
        self.get_revision_ref = GetRevisionRef(factory)
        self.list_part_holdings = ListPartHoldings(factory)
        # The netlist over the unit of work's own nets, parts and pins (11's decision 1).
        self.netlist_pins = self.work.pins
        self.get_netlist = GetNetlist(factory)
        self.add_net = AddNet(factory, self.clock, self.ids)
        self.update_net = UpdateNet(factory, self.clock)
        self.remove_net = RemoveNet(factory, self.clock)
        self.get_pin_usage = GetPinUsage(factory)

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
            get_bom=self.get_bom,
            add_bom_line=self.add_bom_line,
            update_bom_line=self.update_bom_line,
            remove_bom_line=self.remove_bom_line,
            reserve_revision=self.reserve_revision,
            cancel_reservation=self.cancel_reservation,
            build_revision=self.build_revision,
            dismantle_revision=self.dismantle_revision,
            get_lifecycle=self.get_lifecycle,
            get_revision_ref=self.get_revision_ref,
            list_part_holdings=self.list_part_holdings,
            get_netlist=self.get_netlist,
            add_net=self.add_net,
            update_net=self.update_net,
            remove_net=self.remove_net,
            get_pin_usage=self.get_pin_usage,
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
