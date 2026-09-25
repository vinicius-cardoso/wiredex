"""In-memory stand-ins for the catalog ports, shared by the use-case tests.

Each store is one workspace's rows, because that is what a real catalog unit of work sees
(ADR 0007): the workspace it was opened for is recorded rather than filtered on, so a test
can still assert that a use case scoped itself to the caller's bench.
"""

from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from types import TracebackType
from typing import Self
from uuid import uuid7

# A clock and an id generator are nobody's module in particular; identity's fakes are
# simply where they already live.
from support.identity import ManualClock, NewIds
from wiredex.catalog.api.router import CatalogUseCases
from wiredex.catalog.application.attributes import (
    DefineAttribute,
    GetCategorySchema,
    RemoveAttribute,
    UpdateAttribute,
)
from wiredex.catalog.application.categories import (
    CreateCategory,
    DeleteCategory,
    ListCategories,
    MoveCategory,
    RenameCategory,
)
from wiredex.catalog.application.parts import (
    DefinePart,
    DeletePart,
    GetPart,
    ListParts,
    UpdatePart,
)
from wiredex.catalog.application.pinouts import GetPinout, ReplacePinout
from wiredex.catalog.application.ports import Page, PartQuery
from wiredex.catalog.domain.category import Category
from wiredex.catalog.domain.part import PartDefinition, PartDetails
from wiredex.catalog.domain.pinout import Pinout
from wiredex.catalog.domain.schema import AttributeDefinition, AttributeValues
from wiredex.catalog.domain.values import (
    AttributeDefinitionId,
    AttributeKey,
    AttributeKind,
    AttributeLabel,
    CategoryId,
    CategoryName,
    Manufacturer,
    Mpn,
    PartDefinitionId,
    PartName,
    Unit,
    WorkspaceId,
)

NOW = datetime(2026, 9, 25, 10, 0, tzinfo=UTC)
BENCH = WorkspaceId(uuid7())
OHM = Unit("Ω")


class InMemoryCategories:
    def __init__(self) -> None:
        self.saved: dict[CategoryId, Category] = {}

    async def add(self, category: Category) -> None:
        self.saved[category.id] = category

    async def get(self, category_id: CategoryId) -> Category | None:
        return self.saved.get(category_id)

    async def all(self) -> list[Category]:
        return list(self.saved.values())

    async def ancestors(self, category_id: CategoryId) -> list[Category]:
        # Root first, as the recursive query returns it: the order a schema resolves in.
        chain: list[Category] = []
        current = self.saved.get(category_id)
        while current is not None and current.parent_id is not None:
            current = self.saved.get(current.parent_id)
            if current is not None:
                chain.append(current)
        chain.reverse()
        return chain

    async def children_of(self, category_id: CategoryId) -> list[Category]:
        return [child for child in self.saved.values() if child.parent_id == category_id]

    async def sibling_named(
        self, parent_id: CategoryId | None, name: CategoryName
    ) -> Category | None:
        siblings = (c for c in self.saved.values() if c.parent_id == parent_id and c.name == name)
        return next(siblings, None)

    async def remove(self, category: Category) -> None:
        del self.saved[category.id]

    async def remove_all(self) -> None:
        self.saved.clear()


class InMemoryAttributeDefinitions:
    def __init__(self) -> None:
        self.saved: dict[AttributeDefinitionId, AttributeDefinition] = {}

    async def add(self, definition: AttributeDefinition) -> None:
        self.saved[definition.id] = definition

    async def get(self, definition_id: AttributeDefinitionId) -> AttributeDefinition | None:
        return self.saved.get(definition_id)

    async def of_categories(self, category_ids: Sequence[CategoryId]) -> list[AttributeDefinition]:
        wanted = set(category_ids)
        return [d for d in self.saved.values() if d.category_id in wanted]

    async def remove(self, definition: AttributeDefinition) -> None:
        del self.saved[definition.id]

    async def remove_all(self) -> None:
        self.saved.clear()


class InMemoryPinouts:
    """One pinout per part, as the `pins` table holds one group of rows per part."""

    def __init__(self) -> None:
        self.saved: dict[PartDefinitionId, Pinout] = {}

    async def of_part(self, part_id: PartDefinitionId) -> Pinout:
        return self.saved.get(part_id, Pinout.empty())

    async def replace(self, part_id: PartDefinitionId, pinout: Pinout) -> None:
        # The whole table at once, as the DELETE and the bulk INSERT do: no pin of the old
        # pinout can survive a replace, whatever its number.
        self.saved[part_id] = pinout

    async def count_of(self, part_id: PartDefinitionId) -> int:
        return len(self.saved.get(part_id, Pinout.empty()))

    def drop(self, part_id: PartDefinitionId) -> None:
        """What the composite foreign key's ON DELETE CASCADE does (requirement 1.7)."""
        self.saved.pop(part_id, None)


class InMemoryPartDefinitions:
    def __init__(self, pinouts: InMemoryPinouts) -> None:
        self.saved: dict[PartDefinitionId, PartDefinition] = {}
        # The pins go when the part goes, because in Postgres they do: a fake that kept them
        # would let a use case relying on the cascade look correct here and leak rows there.
        self._pinouts = pinouts

    async def add(self, part: PartDefinition) -> None:
        self.saved[part.id] = part

    async def get(self, part_id: PartDefinitionId) -> PartDefinition | None:
        return self.saved.get(part_id)

    async def page(self, query: PartQuery) -> Page[PartDefinition]:
        # By id, which for UUIDv7 is by when the part was defined, so the cursor is an id.
        ordered = sorted(self.saved.values(), key=lambda part: part.id)
        matching = [
            part
            for part in ordered
            if _matches(query, part) and (query.after is None or part.id > query.after)
        ]
        window = tuple(matching[: query.limit])
        more = len(matching) > len(window)
        return Page(window, window[-1].id if more and window else None)

    async def with_mpn(self, manufacturer: Manufacturer | None, mpn: Mpn) -> PartDefinition | None:
        wanted = (_folded(manufacturer), mpn.fold())
        return next((p for p in self.saved.values() if _mpn_key(p) == wanted), None)

    async def count_in(self, category_ids: Sequence[CategoryId]) -> int:
        wanted = set(category_ids)
        return sum(1 for part in self.saved.values() if part.category_id in wanted)

    async def counts_by_category(self) -> dict[CategoryId, int]:
        return dict(Counter(part.category_id for part in self.saved.values()))

    async def remove(self, part: PartDefinition) -> None:
        del self.saved[part.id]
        self._pinouts.drop(part.id)

    async def remove_all(self) -> None:
        # Through `remove`, so a demo bench being restored drops its sample pinouts too.
        for part in list(self.saved.values()):
            await self.remove(part)


def _matches(query: PartQuery, part: PartDefinition) -> bool:
    if query.category_id is not None and part.category_id != query.category_id:
        return False
    if query.text is None:
        return True
    return query.text.lower() in part.name.value.lower()


def _mpn_key(part: PartDefinition) -> tuple[str, str] | None:
    """What the partial unique index compares, or None for a part the index doesn't cover."""
    if part.mpn is None:
        return None
    return _folded(part.manufacturer), part.mpn.fold()


def _folded(manufacturer: Manufacturer | None) -> str:
    # lower(coalesce(manufacturer, '')), as the index spells it.
    return "" if manufacturer is None else manufacturer.value.lower()


class InMemoryCatalog:
    """A unit of work over shared in-memory stores; counts commits and who it was opened for."""

    def __init__(self) -> None:
        self.categories = InMemoryCategories()
        self.attribute_definitions = InMemoryAttributeDefinitions()
        self.pinouts = InMemoryPinouts()
        self.parts = InMemoryPartDefinitions(self.pinouts)
        self.commits = 0
        self.opened_for: list[WorkspaceId] = []

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


class World:
    """The catalog fakes over a bench that already holds *Passives → Resistors*.

    The seed is written straight to the stores, not through use cases: a test of one use
    case shouldn't depend on another one working, and the tree is the same either way.
    """

    def __init__(self) -> None:
        self.catalog = InMemoryCatalog()
        self.clock = ManualClock(NOW)
        self.ids = NewIds()
        self.passives = self.add_category("Passives")
        self.resistors = self.add_category("Resistors", self.passives)
        self.resistance = self.add_attribute(self.resistors, "resistance", required=True)
        work = self.catalog.for_workspace
        self.create_category = CreateCategory(work, self.clock, self.ids)
        self.rename_category = RenameCategory(work)
        self.move_category = MoveCategory(work)
        self.delete_category = DeleteCategory(work)
        self.list_categories = ListCategories(work)
        self.define_attribute = DefineAttribute(work, self.ids)
        self.update_attribute = UpdateAttribute(work)
        self.remove_attribute = RemoveAttribute(work)
        self.get_category_schema = GetCategorySchema(work)
        self.define_part = DefinePart(work, self.clock, self.ids)
        self.update_part = UpdatePart(work, self.clock)
        self.get_part = GetPart(work)
        self.list_parts = ListParts(work)
        self.delete_part = DeletePart(work)
        self.get_pinout = GetPinout(work)
        self.replace_pinout = ReplacePinout(work, self.clock)

    def catalog_use_cases(self) -> CatalogUseCases:
        """What `create_router` takes, so the API test mounts these same fakes."""
        return CatalogUseCases(
            create_category=self.create_category,
            rename_category=self.rename_category,
            move_category=self.move_category,
            delete_category=self.delete_category,
            list_categories=self.list_categories,
            define_attribute=self.define_attribute,
            update_attribute=self.update_attribute,
            remove_attribute=self.remove_attribute,
            get_category_schema=self.get_category_schema,
            define_part=self.define_part,
            update_part=self.update_part,
            get_part=self.get_part,
            list_parts=self.list_parts,
            delete_part=self.delete_part,
        )

    def add_category(self, name: str, parent: Category | None = None) -> Category:
        category = Category(
            CategoryId(uuid7()),
            BENCH,
            None if parent is None else parent.id,
            CategoryName(name),
            self.clock.now(),
        )
        self.catalog.categories.saved[category.id] = category
        return category

    def add_attribute(
        self, category: Category, key: str, *, required: bool = False
    ) -> AttributeDefinition:
        """A seeded number attribute in ohms — the resistance every test bench needs."""
        definition = AttributeDefinition(
            AttributeDefinitionId(uuid7()),
            category.workspace_id,
            category.id,
            AttributeKey(key),
            AttributeLabel(key.capitalize()),
            AttributeKind.NUMBER,
            OHM,
            required,
        )
        self.catalog.attribute_definitions.saved[definition.id] = definition
        return definition

    def add_part(
        self,
        category: Category,
        name: str = "R 4k7 0805",
        attributes: AttributeValues | None = None,
    ) -> PartDefinition:
        part = PartDefinition.define(
            PartDefinitionId(uuid7()),
            category,
            PartDetails(PartName(name)),
            AttributeValues() if attributes is None else attributes,
            self.clock.now(),
        )
        self.catalog.parts.saved[part.id] = part
        return part
