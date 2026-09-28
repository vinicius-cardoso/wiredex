"""A revision's bill of materials: read it with its shortage report, add, edit and remove its
lines, and say which BOMs name a part.

Every write takes the project's lock before it reads the revision's status and its lines
(decision 12), so two writes to one BOM, or a write and 10's transitions, take turns: the
draft check and the designator check see the BOM as the previous change left it. The part is
asked about before the unit of work opens, as `ReceiveStock` asks `Parts`, so no lock is held
across another module's read.
"""

from collections.abc import Callable

from wiredex.projects.application.ports import (
    BomUnitOfWork,
    BomUses,
    BomView,
    NewBomLine,
    PartLookup,
    StockLevels,
)
from wiredex.projects.application.revisions import load_revision, lock_revision
from wiredex.projects.domain.bom import BomLine
from wiredex.projects.domain.errors import UnknownPartError
from wiredex.projects.domain.shortage import ShortageReport
from wiredex.projects.domain.values import BomLineId, PartId, RevisionId, WorkspaceId
from wiredex.shared_kernel.application.ports import Clock, IdGenerator

type BomUnitOfWorkFactory = Callable[[WorkspaceId], BomUnitOfWork]


class GetBom:
    """A revision's lines and their shortage report, computed now and stored nowhere (6.7).

    A fixed number of reads whatever the BOM's size (12.3): the revision and its lines here,
    then one question to the catalog and one to the stock for every part at once, and neither
    for an empty BOM.
    """

    def __init__(
        self, unit_of_work: BomUnitOfWorkFactory, parts: PartLookup, stock: StockLevels
    ) -> None:
        self._unit_of_work = unit_of_work
        self._parts = parts
        self._stock = stock

    async def __call__(self, workspace_id: WorkspaceId, revision_id: RevisionId) -> BomView:
        async with self._unit_of_work(workspace_id) as work:
            revision = await load_revision(work, revision_id)
            bom = await work.bom_lines.of_revision(revision.id)
        # Asked after the unit of work is left: it only read, and the other modules' reads
        # run in transactions of their own (decision 1).
        part_ids = bom.part_ids()
        if not part_ids:
            return BomView(revision, bom, ShortageReport.of(bom, {}, {}))
        facts = await self._parts.describe(workspace_id, part_ids)
        available = await self._stock.available(workspace_id, part_ids)
        return BomView(revision, bom, ShortageReport.of(bom, facts, available))


class AddBomLine:
    """A line after the revision's others, while it is a draft (requirements 4.1, 5.1)."""

    def __init__(
        self,
        unit_of_work: BomUnitOfWorkFactory,
        parts: PartLookup,
        clock: Clock,
        ids: IdGenerator,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._parts = parts
        self._clock = clock
        self._ids = ids

    async def __call__(
        self, workspace_id: WorkspaceId, revision_id: RevisionId, new: NewBomLine
    ) -> BomLine:
        await _ensure_known(self._parts, workspace_id, new.part_id)
        async with self._unit_of_work(workspace_id) as work:
            revision = await lock_revision(work, revision_id)
            revision.ensure_content_editable()
            content = new.content()
            bom = await work.bom_lines.of_revision(revision.id)
            now = self._clock.now()
            line = BomLine.on(revision, BomLineId(self._ids.new_id()), content, now)
            bom.with_line(line)
            await work.bom_lines.add(line)
            revision.touch(now)
            await work.commit()
            return line


class UpdateBomLine:
    """Replaces a line's part, designators, quantity and notes whole (requirement 4.9).

    The part is asked about even when it didn't change, so a line whose part a race deleted
    can't be saved until it names a part the catalog holds; it can always be removed.
    """

    def __init__(self, unit_of_work: BomUnitOfWorkFactory, parts: PartLookup, clock: Clock) -> None:
        self._unit_of_work = unit_of_work
        self._parts = parts
        self._clock = clock

    async def __call__(
        self,
        workspace_id: WorkspaceId,
        revision_id: RevisionId,
        line_id: BomLineId,
        new: NewBomLine,
    ) -> BomLine:
        await _ensure_known(self._parts, workspace_id, new.part_id)
        async with self._unit_of_work(workspace_id) as work:
            revision = await lock_revision(work, revision_id)
            revision.ensure_content_editable()
            bom = await work.bom_lines.of_revision(revision.id)
            before = bom.line(line_id)
            after = before.revised(new.content())
            if after == before:
                return before
            bom.replacing(after)
            await work.bom_lines.update(before, after)
            revision.touch(self._clock.now())
            await work.commit()
            return after


class RemoveBomLine:
    """A line and its designators, while the revision is a draft (requirement 4.10)."""

    def __init__(self, unit_of_work: BomUnitOfWorkFactory, clock: Clock) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    async def __call__(
        self, workspace_id: WorkspaceId, revision_id: RevisionId, line_id: BomLineId
    ) -> None:
        async with self._unit_of_work(workspace_id) as work:
            revision = await lock_revision(work, revision_id)
            revision.ensure_content_editable()
            bom = await work.bom_lines.of_revision(revision.id)
            await work.bom_lines.remove(bom.line(line_id))
            revision.touch(self._clock.now())
            await work.commit()


class ListPartUses:
    """The BOMs naming a part, read only: what catalog's deletion guard is answered from,
    through bootstrap (decision 13)."""

    def __init__(self, unit_of_work: BomUnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId, part_id: PartId, limit: int) -> BomUses:
        async with self._unit_of_work(workspace_id) as work:
            return await work.bom_lines.uses_of(part_id, limit)


async def _ensure_known(parts: PartLookup, workspace_id: WorkspaceId, part_id: PartId) -> None:
    """Requirement 4.2: a part the workspace's catalog doesn't hold, another workspace's
    included, is refused on the part."""
    if part_id not in await parts.describe(workspace_id, [part_id]):
        raise UnknownPartError("that part isn't in the catalog")
