"""A revision's netlist: read it with what each reference resolves to, and add, edit and
remove its nets (11-netlist-editor).

Every write takes the project's lock before it reads the revision's status, its BOM and its
netlist (decision 9), so net writes, BOM writes and 10's transitions to one project take turns,
and a write checks its new references against the BOM the previous change left. The pinouts
are read on the same session, through the unit of work's `pins` (decision 1): no lock is held
across a second connection.
"""

from collections.abc import Callable

from wiredex.projects.application.ports import NetlistUnitOfWork, NetlistView, Nets, NetWrite
from wiredex.projects.application.revisions import load_revision, lock_revision
from wiredex.projects.domain.bom import BillOfMaterials
from wiredex.projects.domain.errors import PartNotFoundError
from wiredex.projects.domain.netlist import Net, NetContent, NetDraft, Netlist, PinReference
from wiredex.projects.domain.pin_usage import PinUsage
from wiredex.projects.domain.revision import Revision
from wiredex.projects.domain.values import NetId, PartId, RevisionId, WorkspaceId
from wiredex.shared_kernel.application.ports import Clock, IdGenerator

type NetlistUnitOfWorkFactory = Callable[[WorkspaceId], NetlistUnitOfWork]


class GetNetlist:
    """The nets, what each reference resolves to, and what the editor picks from, computed now
    and stored nowhere (requirements 4.3, 7). A fixed number of reads whatever the sizes (7.3):
    the revision, the BOM, the netlist, the BOM's parts and their pinouts, all on one session."""

    def __init__(self, unit_of_work: NetlistUnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId, revision_id: RevisionId) -> NetlistView:
        async with self._unit_of_work(workspace_id) as work:
            revision = await load_revision(work, revision_id)
            bom = await work.bom_lines.of_revision(revision.id)
            netlist = await work.nets.of_revision(revision.id)
            part_ids = bom.part_ids()
            parts = await work.parts.describe(part_ids) if part_ids else {}
            pins = await work.pins.of_parts(list(parts)) if parts else {}
        return NetlistView(revision, bom, netlist, parts, pins)


class GetPinUsage:
    """What is wired to each pin of a part, across the workspace's revisions of every status
    (12-wiring-validation requirement 7): the part, its pinout and its uses, three reads on one
    session whatever their number."""

    def __init__(self, unit_of_work: NetlistUnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId, part_id: PartId) -> PinUsage:
        async with self._unit_of_work(workspace_id) as work:
            part = (await work.parts.describe([part_id])).get(part_id)
            if part is None:
                raise PartNotFoundError("that part doesn't exist")
            pinout = (await work.pins.of_parts([part_id])).get(part_id)
            uses = await work.nets.uses_of_part(part_id)
        return PinUsage.of(part, pinout, uses)


class AddNet:
    """A net after the revision's others, while it is a draft (requirements 1.1, 3, 5.1)."""

    def __init__(
        self, unit_of_work: NetlistUnitOfWorkFactory, clock: Clock, ids: IdGenerator
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._ids = ids

    async def __call__(
        self, workspace_id: WorkspaceId, revision_id: RevisionId, draft: NetDraft
    ) -> NetWrite:
        async with self._unit_of_work(workspace_id) as work:
            revision = await lock_revision(work, revision_id)
            revision.ensure_content_editable()
            bom = await work.bom_lines.of_revision(revision.id)
            netlist = await work.nets.of_revision(revision.id)
            content = await _content(work, bom, draft, frozenset())
            now = self._clock.now()
            net = Net.on(revision, NetId(self._ids.new_id()), content, now)
            netlist = netlist.with_net(net)
            await work.nets.add(net)
            revision.touch(now)
            view = await _view_of(work, revision, bom, netlist)
            await work.commit()
            return NetWrite(net, view)


class UpdateNet:
    """Replaces a net's name, color, notes and pins whole (requirement 1.9), keeping the
    references it already held as they are (3.8). The same content commits nothing."""

    def __init__(self, unit_of_work: NetlistUnitOfWorkFactory, clock: Clock) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    async def __call__(
        self,
        workspace_id: WorkspaceId,
        revision_id: RevisionId,
        net_id: NetId,
        draft: NetDraft,
    ) -> NetWrite:
        async with self._unit_of_work(workspace_id) as work:
            revision = await lock_revision(work, revision_id)
            revision.ensure_content_editable()
            bom = await work.bom_lines.of_revision(revision.id)
            netlist = await work.nets.of_revision(revision.id)
            before = netlist.net(net_id)
            kept = frozenset(before.content.pins)
            after = before.revised(await _content(work, bom, draft, kept))
            if after == before:
                return NetWrite(before, await _view_of(work, revision, bom, netlist))
            netlist = netlist.replacing(after)
            await work.nets.update(before, after)
            revision.touch(self._clock.now())
            view = await _view_of(work, revision, bom, netlist)
            await work.commit()
            return NetWrite(after, view)


class RemoveNet:
    """A net and its references, while the revision is a draft (requirement 1.10)."""

    def __init__(self, unit_of_work: NetlistUnitOfWorkFactory, clock: Clock) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    async def __call__(
        self, workspace_id: WorkspaceId, revision_id: RevisionId, net_id: NetId
    ) -> None:
        async with self._unit_of_work(workspace_id) as work:
            revision = await lock_revision(work, revision_id)
            revision.ensure_content_editable()
            netlist = await work.nets.of_revision(revision.id)
            await work.nets.remove(netlist.net(net_id))
            revision.touch(self._clock.now())
            await work.commit()


class CopyNetlist:
    """What a fork copies second, after the BOM: the source's nets, net for net and in order,
    their references as stored, unresolved ones included (decision 10).

    A `RevisionContent`, bound to the fork's transaction by whoever builds the unit of work. The
    fork's BOM is a copy of the source's, so each reference resolves in the fork as it did in
    the source. It never commits: the fork's unit of work does.
    """

    def __init__(self, nets: Nets, ids: IdGenerator) -> None:
        self._nets = nets
        self._ids = ids

    async def copy(self, source: Revision, target: Revision) -> None:
        netlist = await self._nets.of_revision(source.id)
        copies = [net.copied_to(target, NetId(self._ids.new_id())) for net in netlist.nets]
        if copies:
            await self._nets.add_all(copies)


async def _content(
    work: NetlistUnitOfWork,
    bom: BillOfMaterials,
    draft: NetDraft,
    kept: frozenset[PinReference],
) -> NetContent:
    """The draft finished against the BOM and the pinouts of the parts behind its new
    references only, so an edit that adds one reference reads one part's pins."""
    part_ids: list[PartId] = []
    for typed in draft.new_references(kept):
        line = bom.line_with(typed.designator)
        if line is not None and line.content.part_id not in part_ids:
            part_ids.append(line.content.part_id)
    parts = await work.parts.describe(part_ids) if part_ids else {}
    pins = await work.pins.of_parts(list(parts)) if parts else {}
    return draft.content(bom, parts, pins, kept)


async def _view_of(
    work: NetlistUnitOfWork, revision: Revision, bom: BillOfMaterials, netlist: Netlist
) -> NetlistView:
    """The netlist as the write left it, resolved against the same transaction's reads."""
    part_ids = bom.part_ids()
    parts = await work.parts.describe(part_ids) if part_ids else {}
    pins = await work.pins.of_parts(list(parts)) if parts else {}
    return NetlistView(revision, bom, netlist, parts, pins)
