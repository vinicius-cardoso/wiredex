"""What to reorder: the parts whose stock is below the minimum set for them (24-minimum-stock).

A part's minimum is its own when it sets one, else its category's default, the nearest set
along the chain. Zero, set on either, means the part isn't watched. A category that isn't
stocked is never watched: its parts are consumables nobody counts (09's decision 2).
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum

from wiredex.catalog.domain.category import Category, CategoryFlags
from wiredex.catalog.domain.part import PartDefinition
from wiredex.catalog.domain.values import CategoryId, PartDefinitionId


class StockBasis(StrEnum):
    """What a minimum is compared against: what is free, on hand and not reserved for a
    build, or everything on hand, reserved or not. A workspace's choice; free unless it says
    otherwise, since parts promised to a build can't be used for the next one."""

    FREE = "free"
    TOTAL = "total"


@dataclass(frozen=True, slots=True)
class Minimum:
    """The minimum a part is held to, and the category it came from when it isn't its own."""

    quantity: int
    inherited_from: Category | None = None


def minimum_of(
    part: PartDefinition, flags: CategoryFlags, source: Category | None
) -> Minimum | None:
    """The minimum PART is held to, or None when it isn't watched. FLAGS are its category's
    resolved answers and SOURCE the category whose default they carry."""
    if flags.not_stocked:
        return None
    if part.minimum_stock is not None:
        return Minimum(part.minimum_stock) if part.minimum_stock > 0 else None
    if flags.minimum_stock:
        return Minimum(flags.minimum_stock, source)
    return None


def default_source(category: Category, by_id: Mapping[CategoryId, Category]) -> Category | None:
    """The category whose minimum CATEGORY's parts inherit: itself or its nearest ancestor
    that sets one."""
    current: Category | None = category
    while current is not None:
        if current.minimum_stock is not None:
            return current
        current = None if current.parent_id is None else by_id.get(current.parent_id)
    return None


@dataclass(frozen=True, slots=True)
class ReorderLine:
    """One part below its minimum: what there is of it, by the workspace's basis, the minimum
    and how many are missing to reach it."""

    part: PartDefinition
    category: Category
    minimum: Minimum
    have: int

    @property
    def missing(self) -> int:
        return self.minimum.quantity - self.have


def reorder_lines(
    watched: Iterable[tuple[PartDefinition, Category, Minimum]],
    have: Mapping[PartDefinitionId, int],
) -> list[ReorderLine]:
    """The watched parts that are below their minimum, the emptiest first: by how much of the
    minimum is there, then by name. A part with no stock at all reads as zero."""
    lines = [
        ReorderLine(part, category, minimum, have.get(part.id, 0))
        for part, category, minimum in watched
        if have.get(part.id, 0) < minimum.quantity
    ]
    return sorted(
        lines,
        key=lambda line: (line.have / line.minimum.quantity, str(line.part.name).casefold()),
    )
