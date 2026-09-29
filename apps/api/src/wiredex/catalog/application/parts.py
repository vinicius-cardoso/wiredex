"""Part definitions: define one, revise one, read one, list them, delete one.

Every write validates the whole attribute map against the category's resolved schema, so a
part is never stored half-valid. Every read reviews it instead of refusing it, so a schema
fixed late costs the owner nothing (design §2.5).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType

from wiredex.catalog.application.attributes import resolve_schema
from wiredex.catalog.application.categories import UnitOfWorkFactory, load_category
from wiredex.catalog.application.ports import CatalogRepositories, Page, PartQuery, PartUses
from wiredex.catalog.domain.category import CategoryFlags, flags_in_tree
from wiredex.catalog.domain.errors import DuplicateMpnError, PartInUseError, PartNotFoundError
from wiredex.catalog.domain.part import PartDefinition, PartDetails
from wiredex.catalog.domain.schema import AttributeProblem
from wiredex.catalog.domain.values import CategoryId, PartDefinitionId, WorkspaceId
from wiredex.shared_kernel.application.ports import Clock, IdGenerator

# What the owner typed, before the schema says what any of it means.
_NOTHING_TYPED: Mapping[str, object] = MappingProxyType({})


@dataclass(frozen=True, slots=True)
class NewPart:
    """A part to define: where it is catalogued, how it is described, what was typed.

    `raw_attributes` stays untyped all the way in, because only the category's resolved
    schema decides what each key means. The coercion belongs to the domain (design §4).
    """

    category_id: CategoryId
    details: PartDetails
    raw_attributes: Mapping[str, object] = field(default=_NOTHING_TYPED)


@dataclass(frozen=True, slots=True)
class PartRevision:
    """What a patch replaces: the details, the whole attribute map, and the category.

    The map is replaced, never merged (requirement 4.8), which is also why saving a part
    that needed review clears every problem at once (requirement 5.6). `category_id` of
    None leaves the part where it is.
    """

    details: PartDetails
    raw_attributes: Mapping[str, object] = field(default=_NOTHING_TYPED)
    category_id: CategoryId | None = None


@dataclass(frozen=True, slots=True)
class PartView:
    """A part as it is read: what no longer fits its schema, and how many pins it has.

    `pin_count` is what lets a part page say "no pinout yet" without asking for the pins
    (requirement 1.8), so `GetPart` counts them and so does `UpdatePart`: an edit leaves the
    pinout exactly where it was, and answering a patch with zero would be a lie.

    It defaults to none for the one view built without counting, the part a caller has just
    defined: pins are only ever written onto a part that already exists, so it has none.
    """

    part: PartDefinition
    problems: tuple[AttributeProblem, ...] = ()
    pin_count: int = 0

    @property
    def needs_review(self) -> bool:
        return bool(self.problems)


class DefinePart:
    def __init__(self, unit_of_work: UnitOfWorkFactory, clock: Clock, ids: IdGenerator) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._ids = ids

    async def __call__(self, workspace_id: WorkspaceId, new: NewPart) -> PartDefinition:
        async with self._unit_of_work(workspace_id) as work:
            part = await define_part(work, new, self._clock, self._ids)
            await work.commit()
            return part


async def define_part(
    work: CatalogRepositories, new: NewPart, clock: Clock, ids: IdGenerator
) -> PartDefinition:
    """Defines the part in a transaction the caller owns, and commits nothing.

    The one write path for a new part: `DefinePart` opens its own transaction around it, and
    `PartDrafts` runs it inside inventory's intake so the part and its stock land together
    (design decision 2). Whichever door a part comes through, it is validated the same way.
    """
    category = await load_category(work, new.category_id)
    # Validated before anything is stored, so a refused part leaves no trace (4.1).
    schema = await resolve_schema(work, category)
    attributes = schema.validate(new.raw_attributes)
    await _check_mpn_free(work, new.details, None)
    part = PartDefinition.define(
        PartDefinitionId(ids.new_id()), category, new.details, attributes, clock.now()
    )
    await work.parts.add(part)
    return part


class UpdatePart:
    """A revised part, answered as it is read: an edit leaves the pinout it had (1.8)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory, clock: Clock) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    async def __call__(
        self, workspace_id: WorkspaceId, part_id: PartDefinitionId, revision: PartRevision
    ) -> PartView:
        async with self._unit_of_work(workspace_id) as work:
            part = await load_part(work, part_id)
            wanted = part.category_id if revision.category_id is None else revision.category_id
            category = await load_category(work, wanted)
            # Against the schema that will apply, which is how a move to a category the
            # values don't fit is refused (requirement 4.10).
            schema = await resolve_schema(work, category)
            attributes = schema.validate(revision.raw_attributes)
            await _check_mpn_free(work, revision.details, part)
            # Counted before the write: `commit()` ends the transaction whose setting
            # row-level security reads, so a count after it would see no workspace at all.
            pins = await work.pinouts.count_of(part.id)
            now = self._clock.now()
            changed = part.revise(revision.details, attributes, now)
            if category.id != part.category_id:
                part.reclassify(category.id, attributes, now)
                changed = True
            if changed:
                await work.commit()
            # No problems: this map was just validated against the schema that applies to it,
            # which is also what clears a part that needed review (requirement 5.6).
            return PartView(part, pin_count=pins)


class GetPart:
    """One part, and what no longer fits its schema. Never refuses a stored part (5.2)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId, part_id: PartDefinitionId) -> PartView:
        async with self._unit_of_work(workspace_id) as work:
            part = await load_part(work, part_id)
            category = await load_category(work, part.category_id)
            schema = await resolve_schema(work, category)
            # Counted, not loaded: a part page needs to know whether there is a pin table,
            # and the table itself is a request of its own (requirement 1.8).
            pins = await work.pinouts.count_of(part.id)
            return PartView(part, schema.review(part.attributes), pins)


class ListParts:
    """A page of the workspace's parts (requirement 4.11).

    No schema is resolved here: a list of a hundred rows would otherwise read a hundred
    ancestor chains to say nothing the list shows (requirement 8.2).
    """

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId, query: PartQuery) -> Page[PartDefinition]:
        async with self._unit_of_work(workspace_id) as work:
            return await work.parts.page(query)


@dataclass(frozen=True, slots=True)
class PartDescription:
    """A part as other modules ask about it: the part, and its category's resolved flags."""

    part: PartDefinition
    flags: CategoryFlags


class DescribeParts:
    """Several parts and their resolved flags, in two reads whatever their number (09's 12.3).

    What inventory's `Parts` and projects' `PartLookup` are answered from, through bootstrap.
    A part the workspace doesn't hold is left out, so another workspace's id reads as absent
    and whoever asked decides what that means (09's requirement 9.3).
    """

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(
        self, workspace_id: WorkspaceId, part_ids: Sequence[PartDefinitionId]
    ) -> dict[PartDefinitionId, PartDescription]:
        # Answered without opening a transaction when there is nothing to describe, as
        # `describe_parts` returns early too: the caller may pass an empty list.
        if not part_ids:
            return {}
        async with self._unit_of_work(workspace_id) as work:
            return await describe_parts(work, part_ids)


async def describe_parts(
    work: CatalogRepositories, part_ids: Sequence[PartDefinitionId]
) -> dict[PartDefinitionId, PartDescription]:
    """Describe several parts in a transaction the caller owns, and commit nothing.

    The body of `DescribeParts`, taken out so it can run on a session another module's unit of
    work opened: a build transition describes its BOM's parts on the projects unit of work's
    session, over the `CatalogRepositories` bootstrap binds to it (10-build-lifecycle decision
    8), where `DescribeParts` opens a catalog transaction of its own. Both answer the same, in
    the same two reads whatever the number of parts (09's requirement 12.3): a part the
    workspace doesn't hold is left out, so another workspace's id reads as absent.
    """
    if not part_ids:
        return {}
    parts = await work.parts.with_ids(part_ids)
    if not parts:
        return {}
    # The whole tree, tens of rows read once, where a chain per part would be a recursive
    # query each.
    by_id = {category.id: category for category in await work.categories.all()}
    described: dict[PartDefinitionId, PartDescription] = {}
    for part in parts:
        category = by_id.get(part.category_id)
        # A part's category is always in its own workspace's tree; None only if the tree
        # moved under this read, where the default answer is the safe one.
        flags = CategoryFlags() if category is None else flags_in_tree(category, by_id)
        described[part.id] = PartDescription(part, flags)
    return described


# How many of the BOMs keeping a part the refusal names; the rest it only counts.
NAMED_USES = 3


class DeletePart:
    """A part, unless a bill of materials names it (09's requirements 8.1, 8.2).

    The BOMs are asked about in projects' own transaction, and before this one opens: asked
    inside it, each delete would hold a pooled connection while waiting for a second, and a
    handful at once could empty the pool. The part is still judged first, so a part already
    gone stays a 404 even while a raced line still names it. A line added for the part between
    that answer and the commit can still slip past; it then reads as an unknown part until it
    is pointed elsewhere or removed (09's decision 13).
    """

    def __init__(self, unit_of_work: UnitOfWorkFactory, part_uses: PartUses) -> None:
        self._unit_of_work = unit_of_work
        self._part_uses = part_uses

    async def __call__(self, workspace_id: WorkspaceId, part_id: PartDefinitionId) -> None:
        usage = await self._part_uses.of_part(workspace_id, part_id, NAMED_USES)
        async with self._unit_of_work(workspace_id) as work:
            part = await load_part(work, part_id)
            if usage.total:
                raise PartInUseError(_in_use(part, usage.total), usage)
            await work.parts.remove(part)
            await work.commit()


def _in_use(part: PartDefinition, total: int) -> str:
    if total == 1:
        return f"{part.name} is on a bill of materials; take it off first"
    return f"{part.name} is on {total} bills of materials; take it off them first"


async def load_part(work: CatalogRepositories, part_id: PartDefinitionId) -> PartDefinition:
    """The part, or a 404. Another workspace's id is simply not found (requirement 1.9).

    Public for the same reason `load_category` is: a part's pinout is reached through the
    part, and "no such part" has to read the same whichever door it came through.
    """
    part = await work.parts.get(part_id)
    if part is None:
        raise PartNotFoundError("that part doesn't exist")
    return part


async def _check_mpn_free(
    work: CatalogRepositories, details: PartDetails, part: PartDefinition | None
) -> None:
    """Requirement 4.6, folded as the partial index folds it, so TI/BME280 meets ti/bme280.

    No MPN, no uniqueness to keep: any number of parts may go without one (requirement 4.7).
    `part` is the one being revised, which is never in conflict with itself.
    """
    if details.mpn is None:
        return
    holder = await work.parts.with_mpn(details.manufacturer, details.mpn)
    if holder is not None and holder is not part:
        raise DuplicateMpnError(f"{details.mpn} is already used by {holder.name}")
