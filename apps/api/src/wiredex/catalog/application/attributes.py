"""The fields a category's parts have: define one, edit one, remove one, read them all.

Nothing here ever touches a stored part value. A schema edit is one row, and whether the
parts still fit is a question answered when they are read (design §2.5, requirement 5.1).
"""

from collections import defaultdict
from dataclasses import dataclass

from wiredex.catalog.application.categories import UnitOfWorkFactory, load_category
from wiredex.catalog.application.ports import CatalogUnitOfWork
from wiredex.catalog.domain.category import Category
from wiredex.catalog.domain.errors import (
    AttributeNotFoundError,
    CatalogError,
    DuplicateAttributeKeyError,
)
from wiredex.catalog.domain.schema import AttributeDefinition, AttributeSchema
from wiredex.catalog.domain.values import (
    AttributeDefinitionId,
    AttributeKey,
    AttributeKind,
    AttributeLabel,
    CategoryId,
    Unit,
    WorkspaceId,
)
from wiredex.shared_kernel.application.ports import IdGenerator


@dataclass(frozen=True, slots=True)
class NewAttribute:
    """An attribute to define on a category (requirements 2.1, 2.2)."""

    key: AttributeKey
    label: AttributeLabel
    kind: AttributeKind
    unit: Unit | None = None
    required: bool = False
    options: tuple[str, ...] = ()
    position: int = 0


@dataclass(frozen=True, slots=True)
class AttributeChanges:
    """What a patch may carry. `None` is "not sent", so a field left out is left alone.

    `key` and `kind` are here to be refused, never applied: a form that read them may send
    them back unchanged, but changing either makes it a different attribute under the same
    name (requirement 2.9).
    """

    label: AttributeLabel | None = None
    required: bool | None = None
    options: tuple[str, ...] | None = None
    position: int | None = None
    key: AttributeKey | None = None
    kind: AttributeKind | None = None


@dataclass(frozen=True, slots=True)
class CategorySchema:
    """A category and every field its parts have, its ancestors' included (requirement 2.7).

    Each definition carries the `category_id` it belongs to, which is how the web tells an
    inherited field from the category's own.
    """

    category: Category
    schema: AttributeSchema


class DefineAttribute:
    def __init__(self, unit_of_work: UnitOfWorkFactory, ids: IdGenerator) -> None:
        self._unit_of_work = unit_of_work
        self._ids = ids

    async def __call__(
        self, workspace_id: WorkspaceId, category_id: CategoryId, new: NewAttribute
    ) -> AttributeDefinition:
        async with self._unit_of_work(workspace_id) as work:
            category = await load_category(work, category_id)
            await _check_key_free(work, category, new.key)
            # The definition itself refuses a choice with nothing to choose from (2.3).
            definition = AttributeDefinition(
                AttributeDefinitionId(self._ids.new_id()),
                category.id,
                new.key,
                new.label,
                new.kind,
                new.unit,
                new.required,
                new.options,
                new.position,
            )
            await work.attribute_definitions.add(definition)
            await work.commit()
            return definition


class UpdateAttribute:
    """Label, required, options and position. Stored part values are not touched (2.8)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(
        self,
        workspace_id: WorkspaceId,
        definition_id: AttributeDefinitionId,
        changes: AttributeChanges,
    ) -> AttributeDefinition:
        async with self._unit_of_work(workspace_id) as work:
            definition = await _load(work, definition_id)
            _refuse_immutable(definition, changes)
            if changes.options is not None:
                # The same rule the definition was built under, asked of the new list.
                definition.check_options(changes.options)
            if _apply(definition, changes):
                await work.commit()
            return definition


class RemoveAttribute:
    """Deletes the definition and nothing else (requirement 2.10).

    The values stored under its key stay where they are: they come back as `UNKNOWN_KEY`
    problems when a part is read, so the data is visible and defining the key again brings
    it back to valid (requirement 5.5).
    """

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(
        self, workspace_id: WorkspaceId, definition_id: AttributeDefinitionId
    ) -> None:
        async with self._unit_of_work(workspace_id) as work:
            definition = await _load(work, definition_id)
            await work.attribute_definitions.remove(definition)
            await work.commit()


class GetCategorySchema:
    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId, category_id: CategoryId) -> CategorySchema:
        async with self._unit_of_work(workspace_id) as work:
            category = await load_category(work, category_id)
            return CategorySchema(category, await resolve_schema(work, category))


async def resolve_schema(work: CatalogUnitOfWork, category: Category) -> AttributeSchema:
    """The fields that apply to a category: its ancestors' first, then its own.

    Public because defining an attribute and validating a part ask the same question, and
    "which fields apply here" has to have one answer. The chain is read in one recursive
    query and its definitions in one more (requirement 8.1).
    """
    above = await work.categories.ancestors(category.id)
    chain = [*(ancestor.id for ancestor in above), category.id]
    groups: dict[CategoryId, list[AttributeDefinition]] = defaultdict(list)
    for definition in await work.attribute_definitions.of_categories(chain):
        groups[definition.category_id].append(definition)
    return AttributeSchema.inherited([groups[category_id] for category_id in chain])


async def _load(
    work: CatalogUnitOfWork, definition_id: AttributeDefinitionId
) -> AttributeDefinition:
    definition = await work.attribute_definitions.get(definition_id)
    if definition is None:
        raise AttributeNotFoundError("that attribute doesn't exist")
    return definition


async def _check_key_free(work: CatalogUnitOfWork, category: Category, key: AttributeKey) -> None:
    """The whole chain, not just the category: an inherited key can't be shadowed (2.5, 2.6)."""
    defined = (await resolve_schema(work, category)).get(key)
    if defined is not None:
        where = "here" if defined.category_id == category.id else "on a category above this one"
        raise DuplicateAttributeKeyError(f"{key} is already defined {where}")


def _refuse_immutable(definition: AttributeDefinition, changes: AttributeChanges) -> None:
    """Requirement 2.9, and it says what to do instead, because the data is still fine."""
    if changes.key is not None and changes.key != definition.key:
        raise CatalogError(_advice(definition.key, "key"))
    if changes.kind is not None and changes.kind != definition.kind:
        raise CatalogError(_advice(definition.key, "kind"))


def _advice(key: AttributeKey, what: str) -> str:
    return f"{key}'s {what} can't change: remove the attribute and define a new one"


def _apply(definition: AttributeDefinition, changes: AttributeChanges) -> bool:
    """Writes what the patch carried, and answers whether any of it differed.

    A patch that changes nothing commits nothing, as everywhere else in the catalog.
    """
    label = definition.label if changes.label is None else changes.label
    required = definition.required if changes.required is None else changes.required
    options = definition.options if changes.options is None else changes.options
    position = definition.position if changes.position is None else changes.position
    if (label, required, options, position) == (
        definition.label,
        definition.required,
        definition.options,
        definition.position,
    ):
        return False
    definition.label = label
    definition.required = required
    definition.options = options
    definition.position = position
    return True
