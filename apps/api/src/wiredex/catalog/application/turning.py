"""Whether a change would turn parts into a kind they don't fit.

Two of a category's inherited answers decide what a part may hold. *Tracked individually*
decides how its stock is counted: loose pieces are only changed by the lot operations, which
refuse a unit-tracked part, and units by the unit ones, so a part that changed while holding
stock of the other kind would keep a count nothing reaches. *Mechanical* decides whether it
has pins: a mechanical part has no pinout and is never wired (21-part-kinds), so one that
turned mechanical with either would hold what no page shows.

Three writes change what a part's category answers: setting or clearing the flag, moving a
category under another answer, and filing a part under another category. Each asks here first
and is refused with the parts in the way and what to do about them.
"""

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Literal

from wiredex.catalog.application.ports import CatalogRepositories, PartStock, StockCounted
from wiredex.catalog.domain.category import Category, flags_in_tree
from wiredex.catalog.domain.errors import MiscountedStockError, UnfitMechanicalError
from wiredex.catalog.domain.part import PartDefinition
from wiredex.catalog.domain.values import CategoryId, WorkspaceId

#: How many parts a refusal names before it counts the rest.
NAMED = 3
NOTHING = StockCounted()

#: The two inherited answers a part must fit.
type Flag = Literal["tracked_individually", "mechanical"]


async def turning(
    work: CatalogRepositories, category: Category, changed: Category, flag: Flag
) -> dict[CategoryId, bool]:
    """The categories, from CATEGORY down, whose answer to FLAG would change if CATEGORY were
    as CHANGED is, a copy of it with another flag or another parent, each with the answer it
    would then have. Read from the tree in memory, so CATEGORY itself is untouched until the
    change is known to be safe."""
    tree = {one.id: one for one in await work.categories.all()}
    after = {**tree, category.id: changed}
    turned: dict[CategoryId, bool] = {}
    for category_id in await work.categories.descendants(category.id):
        was = getattr(flags_in_tree(tree[category_id], tree), flag)
        becomes = getattr(flags_in_tree(after[category_id], after), flag)
        if was != becomes:
            turned[category_id] = becomes
    return turned


def with_kind(category: Category, mechanical: bool | None) -> Category:
    """CATEGORY as it would be with that kind, for `turning`."""
    return replace(category, mechanical=mechanical)


def with_tracking(category: Category, tracked: bool | None) -> Category:
    """CATEGORY as it would be with that flag, for `turning`."""
    return replace(category, tracked_individually=tracked)


def under(category: Category, parent_id: CategoryId | None) -> Category:
    """CATEGORY as it would be under that parent, for `turning`."""
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


async def refuse_unfit_categories(
    work: CatalogRepositories, turned: Mapping[CategoryId, bool]
) -> None:
    """Refuses when a part of a category TURNED says becomes mechanical holds what a
    mechanical part can't. A category becoming electronic is never in the way."""
    mechanical = [category_id for category_id, becomes in turned.items() if becomes]
    if mechanical:
        await refuse_unfit_mechanical(work, await work.parts.in_categories(mechanical))


async def refuse_unfit_mechanical(
    work: CatalogRepositories, parts: Sequence[PartDefinition]
) -> None:
    """Refuses when a part in PARTS, each about to be mechanical, has a pinout: a mechanical
    part shows none, so it would be kept where no page reaches it (21's requirement 1.3)."""
    if not parts:
        return
    with_pins = await work.pinouts.of_parts([part.id for part in parts])
    pinned = [part for part in parts if part.id in with_pins]
    if pinned:
        raise UnfitMechanicalError(
            f"{_named(pinned)} {_have(pinned)} a pinout, and a mechanical part has none:"
            " remove the pinout first"
        )


def _have(parts: Sequence[PartDefinition]) -> str:
    return "has" if len(parts) == 1 else "have"


def _named(parts: Sequence[PartDefinition]) -> str:
    names = sorted(str(part.name) for part in parts)
    shown = ", ".join(names[:NAMED])
    return shown if len(names) <= NAMED else f"{shown} and {len(names) - NAMED} more"
