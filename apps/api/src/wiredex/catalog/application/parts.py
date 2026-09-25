"""Part definitions: define one, revise one, read one, list them, delete one.

Every write validates the whole attribute map against the category's resolved schema, so a
part is never stored half-valid. Every read reviews it instead of refusing it, so a schema
fixed late costs the owner nothing (design §2.5).
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from wiredex.catalog.application.attributes import resolve_schema
from wiredex.catalog.application.categories import UnitOfWorkFactory, load_category
from wiredex.catalog.application.ports import CatalogUnitOfWork, Page, PartQuery
from wiredex.catalog.domain.errors import DuplicateMpnError, PartNotFoundError
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
    """A part as it is read, with whatever no longer fits its schema (requirements 5.2, 5.3)."""

    part: PartDefinition
    problems: tuple[AttributeProblem, ...] = ()

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
            category = await load_category(work, new.category_id)
            # Validated before anything is stored, so a refused part leaves no trace (4.1).
            schema = await resolve_schema(work, category)
            attributes = schema.validate(new.raw_attributes)
            await _check_mpn_free(work, new.details, None)
            part = PartDefinition.define(
                PartDefinitionId(self._ids.new_id()),
                category,
                new.details,
                attributes,
                self._clock.now(),
            )
            await work.parts.add(part)
            await work.commit()
            return part


class UpdatePart:
    def __init__(self, unit_of_work: UnitOfWorkFactory, clock: Clock) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    async def __call__(
        self, workspace_id: WorkspaceId, part_id: PartDefinitionId, revision: PartRevision
    ) -> PartDefinition:
        async with self._unit_of_work(workspace_id) as work:
            part = await _load(work, part_id)
            wanted = part.category_id if revision.category_id is None else revision.category_id
            category = await load_category(work, wanted)
            # Against the schema that will apply, which is how a move to a category the
            # values don't fit is refused (requirement 4.10).
            schema = await resolve_schema(work, category)
            attributes = schema.validate(revision.raw_attributes)
            await _check_mpn_free(work, revision.details, part)
            now = self._clock.now()
            changed = part.revise(revision.details, attributes, now)
            if category.id != part.category_id:
                part.reclassify(category.id, attributes, now)
                changed = True
            if changed:
                await work.commit()
            return part


class GetPart:
    """One part, and what no longer fits its schema. Never refuses a stored part (5.2)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId, part_id: PartDefinitionId) -> PartView:
        async with self._unit_of_work(workspace_id) as work:
            part = await _load(work, part_id)
            category = await load_category(work, part.category_id)
            schema = await resolve_schema(work, category)
            return PartView(part, schema.review(part.attributes))


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


class DeletePart:
    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId, part_id: PartDefinitionId) -> None:
        async with self._unit_of_work(workspace_id) as work:
            part = await _load(work, part_id)
            await work.parts.remove(part)
            await work.commit()


async def _load(work: CatalogUnitOfWork, part_id: PartDefinitionId) -> PartDefinition:
    part = await work.parts.get(part_id)
    if part is None:
        raise PartNotFoundError("that part doesn't exist")
    return part


async def _check_mpn_free(
    work: CatalogUnitOfWork, details: PartDetails, part: PartDefinition | None
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
