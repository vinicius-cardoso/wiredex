"""The dashboard's reads of the projects module: the parts tied up in builds, and the drafts
short of parts (18-dashboard).

Each costs a fixed number of statements whatever the bench holds (18's requirement 6) and
answers a page: at most `limit` entries, the ones that matter most, and how many more there
are (decision 4). There is no cursor: the lists are bounded by the bench's builds and drafts,
which are few.
"""

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass

from wiredex.projects.application.ports import (
    BomUnitOfWork,
    BuildUnitOfWork,
    PartHoldingView,
    PartLookup,
    RevisionHolding,
    RevisionRef,
    StockLevels,
)
from wiredex.projects.domain.bom import BillOfMaterials
from wiredex.projects.domain.shortage import PartFacts, PartShortage, ShortageReport, StockStatus
from wiredex.projects.domain.values import PartId, RevisionId, WorkspaceId

type BuildUnitOfWorkFactory = Callable[[WorkspaceId], BuildUnitOfWork]
type BomUnitOfWorkFactory = Callable[[WorkspaceId], BomUnitOfWork]

# A page of the dashboard: 20 entries unless asked otherwise, never more than 100 (decision 4).
DEFAULT_LIMIT = 20
MAX_LIMIT = 100


@dataclass(frozen=True, slots=True)
class TiedUpPart:
    """One part reserved or built revisions hold: how many are reserved, how many are in
    builds, and each revision holding it (18's requirement 1.1)."""

    part_id: PartId
    facts: PartFacts | None  # None for a part the catalog no longer holds (09's unknown)
    reserved: int
    consumed: int
    revisions: tuple[PartHoldingView, ...]  # by project name and label

    @property
    def tied_up(self) -> int:
        return self.reserved + self.consumed


@dataclass(frozen=True, slots=True)
class TiedUpParts:
    """The parts tied up most, and how many more there are (18's requirement 1.3)."""

    parts: tuple[TiedUpPart, ...]
    more: int


@dataclass(frozen=True, slots=True)
class ShortRevision:
    """A draft whose BOM is short of a stocked part or names one the catalog no longer holds,
    with 09's report, the one its BOM page shows (18's requirement 2.1)."""

    revision: RevisionRef
    report: ShortageReport

    @property
    def missing(self) -> tuple[PartShortage, ...]:
        """The parts short or unknown, in the order the BOM first names them."""
        return tuple(part for part in self.report.parts if part.status in _MISSING)


@dataclass(frozen=True, slots=True)
class ShortRevisions:
    """The drafts short of parts, by project name and label, and how many more there are (18's
    requirement 2.3)."""

    revisions: tuple[ShortRevision, ...]
    more: int


_MISSING = frozenset({StockStatus.SHORT, StockStatus.UNKNOWN_PART})


class ListTiedUpParts:
    """Every part a reserved or built revision holds, the most tied up first (18's
    requirements 1.1 to 1.4), in one transaction of the build unit of work.

    Three reads whatever the bench holds (18's requirement 6.1): the workspace's holdings
    folded from one grouped ledger read, the refs of every revision holding something, and the
    catalog's facts of every part held. The last two are skipped when nothing is held.
    """

    def __init__(self, unit_of_work: BuildUnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId, limit: int = DEFAULT_LIMIT) -> TiedUpParts:
        async with self._unit_of_work(workspace_id) as work:
            by_part = await work.stock.holdings_by_part()
            if not by_part:
                return TiedUpParts((), 0)
            refs = await work.revisions.refs(_holding_revisions(by_part))
            facts = await work.parts.describe(list(by_part))
        parts = [
            part
            for part_id, holdings in by_part.items()
            if (part := _tied_up(part_id, holdings, refs, facts.get(part_id))) is not None
        ]
        parts.sort(key=_most_tied_up_first)
        return TiedUpParts(tuple(parts[:limit]), max(len(parts) - limit, 0))


class ListShortRevisions:
    """Every draft whose BOM 09's report doesn't call complete, by project name and label
    (18's requirements 2.1 to 2.4).

    The drafts and their BOMs are read in one projects transaction, three reads whatever their
    number, and the transaction is closed before the catalog and the stock are each asked once
    for every part those BOMs name, in transactions of their own (requirement 6.2). Each
    draft's report then runs against the same available stock, as its own BOM page would show
    it (decision 5). A draft whose BOM is covered, holds only consumables or is empty is
    complete, so left out (requirement 2.2).
    """

    def __init__(
        self, unit_of_work: BomUnitOfWorkFactory, parts: PartLookup, stock: StockLevels
    ) -> None:
        self._unit_of_work = unit_of_work
        self._parts = parts
        self._stock = stock

    async def __call__(
        self, workspace_id: WorkspaceId, limit: int = DEFAULT_LIMIT
    ) -> ShortRevisions:
        async with self._unit_of_work(workspace_id) as work:
            drafts = await work.revisions.drafts()
            boms = (
                await work.bom_lines.of_revisions([draft.revision_id for draft in drafts])
                if drafts
                else {}
            )
        part_ids = _named_parts(boms.values())
        if not part_ids:
            return ShortRevisions((), 0)
        facts = await self._parts.describe(workspace_id, part_ids)
        available = await self._stock.available(workspace_id, part_ids)
        short = [
            ShortRevision(draft, report)
            for draft in drafts
            if (bom := boms.get(draft.revision_id)) is not None
            and not (report := ShortageReport.of(bom, facts, available)).summary.complete
        ]
        short.sort(
            key=lambda found: (found.revision.project_name.fold(), found.revision.label.fold())
        )
        return ShortRevisions(tuple(short[:limit]), max(len(short) - limit, 0))


def _holding_revisions(by_part: Mapping[PartId, Sequence[RevisionHolding]]) -> list[RevisionId]:
    """Every revision holding some part, once, in a stable order."""
    return sorted({holding.revision_id for holdings in by_part.values() for holding in holdings})


def _named_parts(boms: Iterable[BillOfMaterials]) -> list[PartId]:
    """Every part the BOMs name, once, in the order they first appear."""
    seen: dict[PartId, None] = {}
    for bom in boms:
        for part_id in bom.part_ids():
            seen.setdefault(part_id, None)
    return list(seen)


def _tied_up(
    part_id: PartId,
    holdings: Sequence[RevisionHolding],
    refs: Mapping[RevisionId, RevisionRef],
    facts: PartFacts | None,
) -> TiedUpPart | None:
    """The part with what its revisions hold. A revision whose ref isn't found, its project
    gone between the two reads, is left out, as 10's part holdings leave it; a part none of
    whose revisions is found is left out too."""
    views = [
        PartHoldingView(ref, holding.reserved, holding.consumed)
        for holding in holdings
        if (ref := refs.get(holding.revision_id)) is not None
    ]
    if not views:
        return None
    views.sort(key=lambda view: (view.revision.project_name.fold(), view.revision.label.fold()))
    return TiedUpPart(
        part_id=part_id,
        facts=facts,
        reserved=sum(view.reserved for view in views),
        consumed=sum(view.consumed for view in views),
        revisions=tuple(views),
    )


def _most_tied_up_first(part: TiedUpPart) -> tuple[int, bool, str, str]:
    # Most tied up first, then by name folded; a part the catalog no longer holds has no name,
    # so it comes after the named ones tied up as much. The id keeps one order between equals.
    name = "" if part.facts is None else part.facts.name.casefold()
    return (-part.tied_up, part.facts is None, name, str(part.part_id))
