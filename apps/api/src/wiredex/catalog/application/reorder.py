"""The reorder list, and one part's standing against its minimum (24-minimum-stock)."""

from dataclasses import dataclass

from wiredex.catalog.application.categories import (
    UnitOfWorkFactory,
    load_category,
    resolve_flags,
)
from wiredex.catalog.application.ports import CatalogRepositories, PartStock, StockBasisOf
from wiredex.catalog.domain.category import Category, flags_in_tree
from wiredex.catalog.domain.part import PartDefinition
from wiredex.catalog.domain.reorder import (
    Minimum,
    ReorderLine,
    StockBasis,
    default_source,
    minimum_of,
    reorder_lines,
)
from wiredex.catalog.domain.values import WorkspaceId


@dataclass(frozen=True, slots=True)
class ReorderView:
    """The parts below their minimum, the emptiest first, and what they were compared by."""

    basis: StockBasis
    lines: list[ReorderLine]


class ListReorder:
    """Every part below its minimum, in three reads whatever the number of parts: the category
    tree, the parts that may be watched, and their stock by the workspace's basis."""

    def __init__(
        self, unit_of_work: UnitOfWorkFactory, part_stock: PartStock, basis_of: StockBasisOf
    ) -> None:
        self._unit_of_work = unit_of_work
        self._part_stock = part_stock
        self._basis_of = basis_of

    async def __call__(self, workspace_id: WorkspaceId) -> ReorderView:
        basis = await self._basis_of(workspace_id)
        async with self._unit_of_work(workspace_id) as work:
            tree = {category.id: category for category in await work.categories.all()}
            defaulted = [
                category.id
                for category in tree.values()
                if flags_in_tree(category, tree).minimum_stock
            ]
            watched: list[tuple[PartDefinition, Category, Minimum]] = []
            for part in await work.parts.watched(defaulted):
                category = tree[part.category_id]
                minimum = minimum_of(
                    part, flags_in_tree(category, tree), default_source(category, tree)
                )
                if minimum is not None:
                    watched.append((part, category, minimum))
        have = await self._part_stock.level(
            workspace_id, [part.id for part, _, _ in watched], basis
        )
        return ReorderView(basis, reorder_lines(watched, have))


async def minimum_for(work: CatalogRepositories, part: PartDefinition) -> Minimum | None:
    """The minimum one part is held to, read along its category's chain: what its page shows
    beside its stock."""
    category = await load_category(work, part.category_id)
    chain = [*await work.categories.ancestors(category.id), category]
    source = next((node for node in reversed(chain) if node.minimum_stock is not None), None)
    return minimum_of(part, await resolve_flags(work, category), source)
