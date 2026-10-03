"""The build lifecycle: reserve, cancel, build and dismantle a revision, and read what it
holds (decision 11).

Each transition is one use case over a `BuildUnitOfWork`, the projects unit of work that also
exposes inventory's stock and catalog's parts on its own session (decision 8). Each opens one
unit of work, takes 09's `lock_revision` first — which answers 404 for a revision the workspace
doesn't hold (requirements 1.7, 11.3) — calls `revision.ensure_allows`, runs its stock step,
calls `revision.move` with the time the step stamped, and commits once, so the status, the
movements, the balances, the units and the last change land together (requirement 1.3). A
refusal raises before the commit and the unit of work rolls the session back, so nothing is
written (requirement 1.4). The project row's lock puts transitions and BOM writes to one
project in a line, so a repeated transition sees the status the one before left it and is
refused as not allowed (requirement 1.5).

`ReserveRevision` refuses before it writes, in decision 12's order (the *A reserve* diagram);
cancel, build and dismantle read no catalog and follow what the ledger says the revision holds
(the *A dismantle* diagram, decision 16).
"""

from collections.abc import Callable, Mapping, Sequence

from wiredex.projects.application.ports import (
    BuildUnitOfWork,
    HeldLot,
    HeldPart,
    HeldUnit,
    Lifecycle,
    PartHoldingView,
    RevisionRef,
)
from wiredex.projects.application.revisions import lock_revision
from wiredex.projects.domain.bom import BillOfMaterials
from wiredex.projects.domain.errors import RevisionNotFoundError
from wiredex.projects.domain.lifecycle import (
    EmptyBomError,
    ShortError,
    StockChangedError,
    Transition,
    transitions_from,
)
from wiredex.projects.domain.reservation import Reservation, check_named_units
from wiredex.projects.domain.revision import Revision
from wiredex.projects.domain.shortage import PartFacts, ShortageReport
from wiredex.projects.domain.values import (
    LocationId,
    PartId,
    RevisionId,
    UnitId,
    WorkspaceId,
)

type BuildUnitOfWorkFactory = Callable[[WorkspaceId], BuildUnitOfWork]


class ReserveRevision:
    """A draft revision reserved, its parts set aside or its shortages reported (requirement 2).

    The clock is the stock step's: `available` stamps the reserve's time after the balance
    lock, so the ledger's order is the order the balances changed, and `revision.move` carries
    that instant (requirement 1.3).
    """

    def __init__(self, unit_of_work: BuildUnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(
        self, workspace_id: WorkspaceId, revision_id: RevisionId, named: Sequence[UnitId]
    ) -> Revision:
        async with self._unit_of_work(workspace_id) as work:
            revision = await lock_revision(work, revision_id)
            revision.ensure_allows(Transition.RESERVE)

            bom = await work.bom_lines.of_revision(revision.id)
            needs = _needs(bom)
            if not needs:
                raise EmptyBomError(
                    f"revision {revision.label} has no BOM to reserve", Transition.RESERVE
                )

            facts = await work.parts.describe(needs.keys())
            stocked = _stocked_needs(needs, facts)
            stock = await work.stock.available(stocked.keys(), named)

            check_named_units(stocked, facts, named, stock)
            report = ShortageReport.of(bom, facts, stock.free())
            if not report.summary.complete:
                missing = report.summary.short_parts + report.summary.unknown_parts
                raise ShortError(
                    f"the BOM is short of {missing} part(s)", Transition.RESERVE, report
                )
            if stock.changed:
                raise StockChangedError(
                    "the stock changed while it was read; try again", Transition.RESERVE
                )

            reservation = Reservation.choose(stocked, stock, named)
            await work.stock.reserve(revision.id, reservation)
            revision.move(Transition.RESERVE, stock.now)
            await work.commit()
            return revision


class CancelReservation:
    """A reserved revision cancelled back to draft, its stock released (requirement 4)."""

    def __init__(self, unit_of_work: BuildUnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId, revision_id: RevisionId) -> Revision:
        async with self._unit_of_work(workspace_id) as work:
            revision = await lock_revision(work, revision_id)
            revision.ensure_allows(Transition.CANCEL)
            now = await work.stock.release(revision.id)
            revision.move(Transition.CANCEL, now)
            await work.commit()
            return revision


class BuildRevision:
    """A reserved revision built, its reservation consumed (requirement 5)."""

    def __init__(self, unit_of_work: BuildUnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId, revision_id: RevisionId) -> Revision:
        async with self._unit_of_work(workspace_id) as work:
            revision = await lock_revision(work, revision_id)
            revision.ensure_allows(Transition.BUILD)
            now = await work.stock.consume(revision.id)
            revision.move(Transition.BUILD, now)
            await work.commit()
            return revision


class DismantleRevision:
    """A built revision dismantled, its parts returned to a chosen location (requirement 6)."""

    def __init__(self, unit_of_work: BuildUnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(
        self, workspace_id: WorkspaceId, revision_id: RevisionId, location_id: LocationId
    ) -> Revision:
        async with self._unit_of_work(workspace_id) as work:
            revision = await lock_revision(work, revision_id)
            revision.ensure_allows(Transition.DISMANTLE)
            # The location is checked inside `return_to`, so its 422 comes before any write
            # (requirement 6.1).
            now = await work.stock.return_to(revision.id, location_id)
            revision.move(Transition.DISMANTLE, now)
            await work.commit()
            return revision


class GetLifecycle:
    """A revision's build: status, the transitions it allows, whether it can be deleted, and
    each part it holds, in a fixed number of queries (requirements 10.1, 10.6)."""

    def __init__(self, unit_of_work: BuildUnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId, revision_id: RevisionId) -> Lifecycle:
        async with self._unit_of_work(workspace_id) as work:
            revision = await work.revisions.get(revision_id)
            if revision is None:
                raise RevisionNotFoundError("that revision doesn't exist")
            siblings = await work.revisions.of_project(revision.project_id)
            deletable = revision.status.deletable and len(siblings.items) > 1

            holdings = await work.stock.holdings(revision.id)
            units = await work.stock.units_of(revision.id)
            part_ids = _held_part_ids(holdings.reserved, holdings.consumed, units)
            facts = await work.parts.describe(part_ids) if part_ids else {}

            parts = _held_parts(holdings.reserved, holdings.consumed, units, facts)
            return Lifecycle(
                status=revision.status,
                transitions=transitions_from(revision.status),
                deletable=deletable,
                parts=parts,
            )


class GetRevisionRef:
    """A revision found by its id alone (requirement 10.2), in one query (11.3)."""

    def __init__(self, unit_of_work: BuildUnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId, revision_id: RevisionId) -> RevisionRef:
        async with self._unit_of_work(workspace_id) as work:
            ref = await work.revisions.ref(revision_id)
            if ref is None:
                raise RevisionNotFoundError("that revision doesn't exist")
            return ref


# How many revisions one read names: the boards a list shows at most.
MAX_REVISION_REFS = 200


class GetRevisionRefs:
    """Several revisions found by their ids alone, in one query whatever their number: what a
    list naming the build beside each of its rows reads (the boards list). They come back in
    the order asked, each once; an id the workspace doesn't hold, a revision of a project in the
    trash included, is left out rather than refused, since a list asks for what it shows."""

    def __init__(self, unit_of_work: BuildUnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(
        self, workspace_id: WorkspaceId, revision_ids: Sequence[RevisionId]
    ) -> list[RevisionRef]:
        asked = list(dict.fromkeys(revision_ids))
        if not asked:
            return []
        async with self._unit_of_work(workspace_id) as work:
            refs = await work.revisions.refs(asked)
        return [ref for revision_id in asked if (ref := refs.get(revision_id)) is not None]


class ListPartHoldings:
    """Each revision holding a part, with its ref, ordered by project name and label
    (requirements 10.4, 10.6). A part nothing holds answers an empty list."""

    def __init__(self, unit_of_work: BuildUnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId, part_id: PartId) -> list[PartHoldingView]:
        async with self._unit_of_work(workspace_id) as work:
            holdings = await work.stock.holdings_of_part(part_id)
            if not holdings:
                return []
            refs = await work.revisions.refs([holding.revision_id for holding in holdings])
            views = [
                PartHoldingView(ref, holding.reserved, holding.consumed)
                for holding in holdings
                if (ref := refs.get(holding.revision_id)) is not None
            ]
            views.sort(
                key=lambda view: (
                    view.revision.project_name.fold(),
                    view.revision.label.fold(),
                )
            )
            return views


def _needs(bom: BillOfMaterials) -> dict[PartId, int]:
    """Each part's need summed over the BOM's lines, in the order they first appear."""
    return {need.part_id: need.quantity for need in bom.needs()}


def _stocked_needs(
    needs: Mapping[PartId, int], facts: Mapping[PartId, PartFacts]
) -> dict[PartId, int]:
    """The needs of parts the catalog holds that aren't consumables: what stock is locked for
    and what `choose` takes (requirements 2.4, 2.7). A consumable is never reserved (16), and
    an unknown part carries no stock, so both drop out here and only the shortage report sees
    them."""
    return {
        part_id: quantity
        for part_id, quantity in needs.items()
        if (part := facts.get(part_id)) is not None and not part.not_stocked
    }


def _held_part_ids(
    reserved: Sequence[HeldLot], consumed: Mapping[PartId, int], units: Sequence[HeldUnit]
) -> list[PartId]:
    """Every part a revision holds, once: the parts it reserves, consumed, or holds units of.
    In first-seen order, so the catalog is asked once whatever the number of lots."""
    seen: dict[PartId, None] = {}
    for lot in reserved:
        seen.setdefault(lot.part_id, None)
    for part_id in consumed:
        seen.setdefault(part_id, None)
    for unit in units:
        seen.setdefault(unit.part_id, None)
    return list(seen)


def _held_parts(
    reserved: Sequence[HeldLot],
    consumed: Mapping[PartId, int],
    units: Sequence[HeldUnit],
    facts: Mapping[PartId, PartFacts],
) -> tuple[HeldPart, ...]:
    """One `HeldPart` per part the revision holds, its facts, its reservations by location, its
    consumption and its units, ordered by part name so the page reads in a stable order."""
    reserved_by_part: dict[PartId, list[HeldLot]] = {}
    for lot in reserved:
        reserved_by_part.setdefault(lot.part_id, []).append(lot)
    units_by_part: dict[PartId, list[HeldUnit]] = {}
    for unit in units:
        units_by_part.setdefault(unit.part_id, []).append(unit)

    parts = [
        HeldPart(
            part_id=part_id,
            facts=facts.get(part_id),
            reserved=tuple(
                sorted(reserved_by_part.get(part_id, ()), key=lambda lot: lot.location_code)
            ),
            consumed=consumed.get(part_id, 0),
            units=tuple(sorted(units_by_part.get(part_id, ()), key=lambda unit: unit.code)),
        )
        for part_id in _held_part_ids(reserved, consumed, units)
    ]
    # By part name; a part the catalog no longer holds has no name, so it sorts last.
    parts.sort(key=lambda part: (part.facts is None, part.facts.name if part.facts else ""))
    return tuple(parts)
