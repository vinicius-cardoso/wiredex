"""The category tree: create, rename, move, delete, and read the whole thing.

The tree rules the domain can't answer alone all need a look around — is that name taken
among these siblings, is this parent one of my own descendants, how deep does my subtree
reach — so these use cases are the ones that read and pass it in.
"""

from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass

from wiredex.catalog.application.ports import CatalogUnitOfWork
from wiredex.catalog.domain.category import Category, check_depth
from wiredex.catalog.domain.errors import (
    CategoryInUseError,
    CategoryNotFoundError,
    DuplicateCategoryNameError,
)
from wiredex.catalog.domain.values import CategoryId, CategoryName, WorkspaceId
from wiredex.shared_kernel.application.ports import Clock, IdGenerator

type UnitOfWorkFactory = Callable[[WorkspaceId], CatalogUnitOfWork]


@dataclass(frozen=True, slots=True)
class NewCategory:
    """A category to create: a name, and where it hangs. No parent means a root (1.1, 1.2)."""

    name: CategoryName
    parent_id: CategoryId | None = None


@dataclass(frozen=True, slots=True)
class CategoryNode:
    """A category as the tree shows it, with what requirement 1.11 asks alongside it.

    `part_count` counts the parts classified directly under the category, not its subtree:
    it answers "is there anything in here", which is also what blocks a delete.
    """

    category: Category
    child_count: int
    part_count: int


class CreateCategory:
    def __init__(self, unit_of_work: UnitOfWorkFactory, clock: Clock, ids: IdGenerator) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._ids = ids

    async def __call__(self, workspace_id: WorkspaceId, new: NewCategory) -> Category:
        async with self._unit_of_work(workspace_id) as work:
            parent = await _parent(work, new.parent_id)
            await _check_name_free(work, new.parent_id, new.name)
            check_depth(await _position_under(work, parent))
            category = Category(
                CategoryId(self._ids.new_id()),
                workspace_id,
                new.parent_id,
                new.name,
                self._clock.now(),
            )
            await work.categories.add(category)
            await work.commit()
            return category


class RenameCategory:
    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(
        self, workspace_id: WorkspaceId, category_id: CategoryId, name: CategoryName
    ) -> Category:
        async with self._unit_of_work(workspace_id) as work:
            category = await load_category(work, category_id)
            # Only a real rename asks whether the name is free, because a category is
            # always its own sibling. The entity is what decides something changed, so
            # renaming to the name it already has commits nothing (requirement 1.8).
            if category.name != name:
                await _check_name_free(work, category.parent_id, name)
            if category.rename(name):
                await work.commit()
            return category


class MoveCategory:
    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(
        self, workspace_id: WorkspaceId, category_id: CategoryId, parent_id: CategoryId | None
    ) -> Category:
        async with self._unit_of_work(workspace_id) as work:
            category = await load_category(work, category_id)
            parent = await _parent(work, parent_id)
            if category.parent_id != parent_id:
                await _check_name_free(work, parent_id, category.name)
            position = await _position_under(work, parent)
            # The entity checks its own depth, but only a reader of the tree knows how many
            # levels of descendants ride along with it (requirement 1.6).
            check_depth(position, below=await _subtree_depth(work, category_id))
            # `position` without the parent itself is the parent's own chain, which is what
            # the entity reads to refuse a move under one of its descendants.
            category.move_under(parent, position[:-1])
            await work.commit()
            return category


class DeleteCategory:
    """Refuses rather than cascades: nothing here deletes data another row points at."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId, category_id: CategoryId) -> None:
        async with self._unit_of_work(workspace_id) as work:
            category = await load_category(work, category_id)
            # Which of the two blocks it, because that is what the web has to say (1.9).
            if await work.categories.children_of(category_id):
                raise CategoryInUseError(f"{category.name} still has categories under it")
            if await work.parts.count_in([category_id]):
                raise CategoryInUseError(f"{category.name} still has parts")
            # The category's own definitions go with it (requirement 1.10). The column
            # cascades in PostgreSQL too; saying it here keeps every store in step.
            for definition in await work.attribute_definitions.of_categories([category_id]):
                await work.attribute_definitions.remove(definition)
            await work.categories.remove(category)
            await work.commit()


class ListCategories:
    """The whole tree, flat, each node carrying its counts (requirement 1.11)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId) -> list[CategoryNode]:
        async with self._unit_of_work(workspace_id) as work:
            categories = await work.categories.all()
            parts = await work.parts.counts_by_category()
        children = Counter(c.parent_id for c in categories if c.parent_id is not None)
        # Siblings come out alphabetically; the web nests them by parent id.
        return [
            CategoryNode(category, children[category.id], parts.get(category.id, 0))
            for category in sorted(categories, key=_by_name)
        ]


async def load_category(work: CatalogUnitOfWork, category_id: CategoryId) -> Category:
    """The category, or a 404. Another workspace's id is simply not found (requirement 6.4).

    Public because attributes and parts are always reached through their category, and
    "no such category" has to read the same whichever door it came through.
    """
    category = await work.categories.get(category_id)
    if category is None:
        raise CategoryNotFoundError("that category doesn't exist")
    return category


async def _parent(work: CatalogUnitOfWork, parent_id: CategoryId | None) -> Category | None:
    """The parent a command names, or None for the root. A named parent has to exist."""
    if parent_id is None:
        return None
    return await load_category(work, parent_id)


async def _check_name_free(
    work: CatalogUnitOfWork, parent_id: CategoryId | None, name: CategoryName
) -> None:
    """Requirements 1.3 and 1.7, roots included: two roots are siblings of each other."""
    if await work.categories.sibling_named(parent_id, name) is not None:
        where = "at the root" if parent_id is None else "here"
        raise DuplicateCategoryNameError(f"there is already a {name} {where}")


async def _position_under(work: CatalogUnitOfWork, parent: Category | None) -> list[CategoryId]:
    """The ancestor ids of a category sitting under `parent`: root first, the parent last."""
    if parent is None:
        return []
    above = await work.categories.ancestors(parent.id)
    return [*(ancestor.id for ancestor in above), parent.id]


async def _subtree_depth(work: CatalogUnitOfWork, category_id: CategoryId) -> int:
    """How many levels of descendants a category carries, 0 for a leaf.

    The whole tree in one read, level by level: the depth cap keeps it small, and it is
    cheaper than asking the database for the descendants of every move.
    """
    children: dict[CategoryId | None, list[CategoryId]] = defaultdict(list)
    for category in await work.categories.all():
        children[category.parent_id].append(category.id)
    depth, level = 0, children[category_id]
    while level:
        depth += 1
        level = [child for parent in level for child in children[parent]]
    return depth


def _by_name(category: Category) -> tuple[str, str]:
    # Folded, so *anti-surge* sits next to *Anti-surge*; the id breaks a tie so the order
    # of two categories with one name is still stable.
    return category.name.value.casefold(), str(category.id)
