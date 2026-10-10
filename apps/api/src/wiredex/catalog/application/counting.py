"""Whether a change would leave stock where nothing reaches it.

A part is counted in lots or tracked as units, as its category resolves (05's requirement 6).
Loose pieces are only changed by the lot operations, which refuse a unit-tracked part, and
units by the unit ones. So a part that changes kind while it holds stock of the kind it stops
being keeps that stock, frozen: a count the owner sees and can't correct. Three writes change a
part's kind: setting or clearing a category's flag, moving a category under another answer, and
filing a part under another category. Each asks here first, and is refused with the parts in the
way and what to do about them.
"""

from collections.abc import Mapping
from dataclasses import replace

from wiredex.catalog.application.ports import CatalogRepositories, PartStock, StockCounted
from wiredex.catalog.domain.category import Category, flags_in_tree
from wiredex.catalog.domain.errors import MiscountedStockError
from wiredex.catalog.domain.part import PartDefinition
from wiredex.catalog.domain.values import CategoryId, WorkspaceId

#: How many parts a refusal names before it counts the rest.
NAMED = 3
NOTHING = StockCounted()


async def turning_tracked(
    work: CatalogRepositories, category: Category, changed: Category
) -> dict[CategoryId, bool]:
    """The categories, from CATEGORY down, whose parts would change kind if CATEGORY were as
    CHANGED is, a copy of it with another flag or another parent, each with the answer it
    would then have: True for tracked as units. Read from the tree in memory, so CATEGORY
    itself is untouched until the change is known to be safe."""
    tree = {one.id: one for one in await work.categories.all()}
    after = {**tree, category.id: changed}
    turned: dict[CategoryId, bool] = {}
    for category_id in await work.categories.descendants(category.id):
        was = flags_in_tree(tree[category_id], tree).tracked_individually
        becomes = flags_in_tree(after[category_id], after).tracked_individually
        if was != becomes:
            turned[category_id] = becomes
    return turned


def with_tracking(category: Category, tracked: bool | None) -> Category:
    """CATEGORY as it would be with that flag, for `turning_tracked`."""
    return replace(category, tracked_individually=tracked)


def under(category: Category, parent_id: CategoryId | None) -> Category:
    """CATEGORY as it would be under that parent, for `turning_tracked`."""
    return replace(category, parent_id=parent_id)


async def refuse_miscounted_categories(
    work: CatalogRepositories,
    part_stock: PartStock,
    workspace_id: WorkspaceId,
    turned: Mapping[CategoryId, bool],
) -> None:
    """Refuses when a part of a category in TURNED holds stock of the kind it would stop
    being. Nothing is asked of inventory when no category changes its answer."""
    if not turned:
        return
    parts = await work.parts.in_categories(list(turned))
    await refuse_miscounted(
        part_stock, workspace_id, {part: turned[part.category_id] for part in parts}
    )


async def refuse_miscounted(
    part_stock: PartStock, workspace_id: WorkspaceId, becoming: Mapping[PartDefinition, bool]
) -> None:
    """Refuses when a part in BECOMING, each with whether it would be tracked as units, holds
    loose pieces it would be tracked without, or units it would be counted without."""
    if not becoming:
        return
    counted = await part_stock.counted(workspace_id, [part.id for part in becoming])
    held = {part: counted.get(part.id, NOTHING) for part in becoming}
    loose = [part for part, tracked in becoming.items() if tracked and held[part].loose]
    units = [part for part, tracked in becoming.items() if not tracked and held[part].units]
    if loose:
        raise MiscountedStockError(
            f"{_named(loose)} would be tracked as units while holding stock counted loose:"
            " adjust that stock to zero first, then receive it again as units"
        )
    if units:
        raise MiscountedStockError(
            f"{_named(units)} would be counted in lots while having units: retire or delete"
            " those units first"
        )


def _named(parts: list[PartDefinition]) -> str:
    names = sorted(str(part.name) for part in parts)
    shown = ", ".join(names[:NAMED])
    return shown if len(names) <= NAMED else f"{shown} and {len(names) - NAMED} more"
