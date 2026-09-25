"""What the catalog use cases need from the outside, as Protocols over domain types.

No method takes a workspace: the unit of work is built for one workspace and its
repositories only ever see that workspace's rows (ADR 0007, design §3). That is also why
the unit of work exposes them as read-only properties.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from wiredex.catalog.domain.category import Category
from wiredex.catalog.domain.part import PartDefinition
from wiredex.catalog.domain.pinout import Pinout
from wiredex.catalog.domain.schema import AttributeDefinition
from wiredex.catalog.domain.values import (
    AttributeDefinitionId,
    CategoryId,
    CategoryName,
    Manufacturer,
    Mpn,
    PartDefinitionId,
)
from wiredex.shared_kernel.application.ports import UnitOfWork

DEFAULT_PAGE_SIZE = 50


@dataclass(frozen=True, slots=True)
class PartQuery:
    """One window of the part list: requirement 4.11's filters, and where to carry on from.

    `text` matches a substring of the name. `after` is the last part of the previous page;
    ids are UUIDv7, so ordering by id is ordering by when the part was defined.
    """

    category_id: CategoryId | None = None
    text: str | None = None
    limit: int = DEFAULT_PAGE_SIZE
    after: PartDefinitionId | None = None


@dataclass(frozen=True, slots=True)
class Page[T]:
    """A window of rows and the cursor for the next one, `None` once the last row is in."""

    # A UUID rather than the id type of T: every catalog id is a UUIDv7, and keeping the
    # cursor generic is what lets a second listing reuse this.
    items: tuple[T, ...]
    next_cursor: UUID | None = None


class Categories(Protocol):
    async def add(self, category: Category) -> None: ...

    async def get(self, category_id: CategoryId) -> Category | None: ...

    async def all(self) -> list[Category]:
        """Every category of the workspace, which is what the tree is built from."""
        ...

    async def ancestors(self, category_id: CategoryId) -> list[Category]:
        """The chain above the category, root first, in one round trip (requirement 8.1)."""
        ...

    async def children_of(self, category_id: CategoryId) -> list[Category]: ...

    async def sibling_named(
        self, parent_id: CategoryId | None, name: CategoryName
    ) -> Category | None:
        """The category already using that name under that parent, two roots included.

        `parent_id=None` means among the roots, which the table spells `NULLS NOT DISTINCT`.
        """
        ...

    async def remove(self, category: Category) -> None: ...

    async def remove_all(self) -> None:
        """Every category of the workspace, for a demo bench being restored (ADR 0007)."""
        ...


class AttributeDefinitions(Protocol):
    async def add(self, definition: AttributeDefinition) -> None: ...

    async def get(self, definition_id: AttributeDefinitionId) -> AttributeDefinition | None: ...

    async def of_categories(self, category_ids: Sequence[CategoryId]) -> list[AttributeDefinition]:
        """The definitions of a whole ancestor chain at once, so a schema costs one query."""
        ...

    async def remove(self, definition: AttributeDefinition) -> None: ...

    async def remove_all(self) -> None:
        """Every definition of the workspace, for a demo bench being restored (ADR 0007)."""
        ...


class PartDefinitions(Protocol):
    async def add(self, part: PartDefinition) -> None: ...

    async def get(self, part_id: PartDefinitionId) -> PartDefinition | None: ...

    async def page(self, query: PartQuery) -> Page[PartDefinition]: ...

    async def with_mpn(self, manufacturer: Manufacturer | None, mpn: Mpn) -> PartDefinition | None:
        """The part holding that manufacturer and MPN, compared folded (requirement 4.6).

        The manufacturer is optional because the partial unique index reads a missing one as
        the empty string: otherwise two parts sharing an MPN and no manufacturer would both
        be accepted, since NULL never collides (design §5).
        """
        ...

    async def count_in(self, category_ids: Sequence[CategoryId]) -> int:
        """How many parts hang off these categories, which is what blocks a delete."""
        ...

    async def counts_by_category(self) -> dict[CategoryId, int]:
        """A count per category for the tree (requirement 1.11), in one grouped query."""
        ...

    async def remove(self, part: PartDefinition) -> None: ...

    async def remove_all(self) -> None:
        """Every part of the workspace, for a demo bench being restored (ADR 0007)."""
        ...


class Pinouts(Protocol):
    """A part's pins, read and written as one collection: pinouts are replaced, not patched.

    No `remove`: a deleted part takes its pins with it, in the database through
    `ON DELETE CASCADE` and in the fakes the same way, so nothing here has to remember to.
    """

    async def of_part(self, part_id: PartDefinitionId) -> Pinout:
        """The part's pins in their saved order, empty for a part that has none (1.2)."""
        ...

    async def replace(self, part_id: PartDefinitionId, pinout: Pinout) -> None:
        """Delete the part's pins and insert these, in their order, in one transaction (1.3)."""
        ...

    async def count_of(self, part_id: PartDefinitionId) -> int:
        """How many pins the part has, for a part page that shouldn't read them all (1.8)."""
        ...


class CatalogUnitOfWork(UnitOfWork, Protocol):
    # Read-only properties, not attributes: a protocol attribute would have to match
    # exactly, so SqlCategories wouldn't count as Categories.
    @property
    def categories(self) -> Categories: ...

    @property
    def attribute_definitions(self) -> AttributeDefinitions: ...

    @property
    def parts(self) -> PartDefinitions: ...


class PinoutUnitOfWork(CatalogUnitOfWork, Protocol):
    """A catalog unit of work that also holds the pins: what the pinout use cases take.

    `pinouts` belongs on `CatalogUnitOfWork` with the other three, and moves there as soon as
    the SQL side has a `SqlPinouts` to bind. Until then it would be a promise no unit of work
    over Postgres could keep, so the use cases that need pins ask for it and the rest don't.
    """

    @property
    def pinouts(self) -> Pinouts: ...
