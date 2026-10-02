"""What the catalog use cases need from the outside, as Protocols over domain types.

No method takes a workspace: the unit of work is built for one workspace and its
repositories only ever see that workspace's rows (ADR 0007, design §3). That is also why
the unit of work exposes them as read-only properties.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from wiredex.catalog.domain.category import Category
from wiredex.catalog.domain.part import PartDefinition
from wiredex.catalog.domain.pinout import Pinout
from wiredex.catalog.domain.schema import AttributeDefinition, AttributeSchema
from wiredex.catalog.domain.search import PartSort, SearchCursor, Spec
from wiredex.catalog.domain.usage import PartUsage
from wiredex.catalog.domain.values import (
    AttributeDefinitionId,
    CategoryId,
    CategoryName,
    Manufacturer,
    Mpn,
    PartDefinitionId,
    WorkspaceId,
)
from wiredex.shared_kernel.application.ports import UnitOfWork
from wiredex.shared_kernel.domain.trash import TrashPosition

if TYPE_CHECKING:
    # `Facets` lives next to the use case that builds it (search.py), which imports this
    # module for `Page` and the unit of work: importing it back only under TYPE_CHECKING is
    # what keeps the two files from forming a runtime import cycle. It is only a return
    # annotation here, so a deferred import is all the type checker needs.
    from wiredex.catalog.application.search import Facets

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
class Page[T, C = UUID]:
    """A window of rows and the cursor for the next one, `None` once the last row is in.

    The cursor type is a parameter, defaulting to `UUID`: the plain part list continues from
    the last id it saw (`Page[PartDefinition]`), while a parametric search continues from a
    `SearchCursor` that remembers its sort and its search (`Page[PartDefinition,
    SearchCursor]`). Both are one window of rows and where to carry on from, so both are this.
    """

    items: tuple[T, ...]
    next_cursor: C | None = None


class Categories(Protocol):
    async def add(self, category: Category) -> None: ...

    async def get(self, category_id: CategoryId) -> Category | None: ...

    async def all(self) -> list[Category]:
        """Every category of the workspace, which is what the tree is built from."""
        ...

    async def find(self, text: str, limit: int) -> list[Category]:
        """The categories whose name contains the text, case aside, the ones starting with it
        first, then by name, at most `limit`, in one query (19-command-palette, decision 1)."""
        ...

    async def ancestors(self, category_id: CategoryId) -> list[Category]:
        """The chain above the category, root first, in one round trip (requirement 8.1)."""
        ...

    async def descendants(self, category_id: CategoryId) -> list[CategoryId]:
        """The category and every one under it, in one recursive query (requirement 1.2).

        The mirror of `ancestors`, and the ids alone: a search that includes a category's
        subtree needs which categories are in it, not the categories themselves. The
        category itself is included, so `InCategories` gets the whole set it filters on.
        """
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
    """The workspace's parts. Every read but `with_mpn`, the counts in the trash and the trash's
    own reads leaves a part in the trash out, as a part that doesn't exist (16-soft-delete-and-
    trash, decision 2)."""

    async def add(self, part: PartDefinition) -> None: ...

    async def get(self, part_id: PartDefinitionId) -> PartDefinition | None: ...

    async def locked(self, part_id: PartDefinitionId) -> PartDefinition | None:
        """The live part, its row locked until the transaction ends and read fresh, or None:
        what moving it to the trash takes first (16's decision 3)."""
        ...

    async def with_ids(self, part_ids: Sequence[PartDefinitionId]) -> list[PartDefinition]:
        """The workspace's parts among these ids, in one query; an id it doesn't hold is
        simply absent, in no particular order (09's requirement 12.3)."""
        ...

    async def page(self, query: PartQuery) -> Page[PartDefinition]: ...

    async def find(self, text: str, limit: int) -> list[PartDefinition]:
        """The live parts whose name, MPN or manufacturer contains the text, case aside, the
        ones whose name starts with it first, then by name, at most `limit`, in one query over
        the trigram indexes (19-command-palette, decision 1)."""
        ...

    async def search(
        self, spec: Spec, sort: PartSort, after: SearchCursor | None, limit: int
    ) -> Page[PartDefinition, SearchCursor]:
        """One page of the parts the spec matches, in the sort's order, from the cursor on.

        `spec` is the whole `AllOf` the application built and validated; `sort` orders the
        page with parts missing the sort value last and the id breaking ties; `after`
        continues a previous page. The infrastructure serves this in one query
        (requirement 7.3); the fakes evaluate `matches` and slice in Python.
        """
        ...

    async def facets(self, spec: Spec, schema: AttributeSchema) -> Facets:
        """For each attribute of the schema, what values the matching parts hold.

        `spec` narrows by category, text and pin only — the attribute filters don't reach
        here, so every option stays selectable (requirement 5.2). Each enum option gets its
        count, each boolean its true/false counts, and each number its lowest and highest
        value, or none when no part has one (requirements 5.1, 5.3).
        """
        ...

    async def with_mpn(self, manufacturer: Manufacturer | None, mpn: Mpn) -> PartDefinition | None:
        """The part holding that manufacturer and MPN, compared folded (requirement 4.6), in
        the trash or not: a part in the trash keeps its MPN, as the unique index does (16's
        decision 5).

        The manufacturer is optional because the partial unique index reads a missing one as
        the empty string: otherwise two parts sharing an MPN and no manufacturer would both
        be accepted, since NULL never collides (design §5).
        """
        ...

    async def count_in(self, category_ids: Sequence[CategoryId]) -> int:
        """How many live parts hang off these categories, which is what blocks a delete."""
        ...

    async def count_in_trash(self, category_ids: Sequence[CategoryId]) -> int:
        """How many parts in the trash these categories hold, which blocks a delete too: a part
        is restored into its category (16's decision 6)."""
        ...

    async def counts_by_category(self) -> dict[CategoryId, int]:
        """A count per category for the tree (requirement 1.11), in one grouped query."""
        ...

    async def remove(self, part: PartDefinition) -> None: ...

    async def remove_all(self) -> None:
        """Every part of the workspace, the trash's included, for a demo bench being restored
        (ADR 0007)."""
        ...

    async def trashed(self, before: TrashPosition | None, limit: int) -> list[PartDefinition]:
        """The parts in the trash before the position, newest first, at most `limit` (16's
        decision 9)."""
        ...

    async def in_trash(self, part_id: PartDefinitionId) -> PartDefinition | None:
        """The part if it is in the trash, its row locked and read fresh, or None (16's
        decision 10)."""
        ...

    async def empty_trash(self) -> int:
        """Every part in the trash deleted for good, its pins with it, in one statement; how
        many went."""
        ...

    async def kept(self, part_id: PartDefinitionId) -> bool:
        """Whether the workspace still holds the part, live or in the trash (16's decision 7)."""
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

    async def of_parts(
        self, part_ids: Sequence[PartDefinitionId]
    ) -> dict[PartDefinitionId, Pinout]:
        """Several parts' pins in one query, each in its saved order; a part with none, or one
        the workspace doesn't hold, is absent (11-netlist-editor decision 1)."""
        ...


class CatalogRepositories(Protocol):
    """The catalog's repositories, bound to a transaction that may be someone else's.

    No `commit`: code that takes only this can read and write inside a transaction another
    module opened, and can never end it (design decision 2). `PartDrafts` runs over it inside
    inventory's intake, and the `load_*` and `resolve_*` helpers take it so they serve both.
    """

    # Read-only properties, not attributes: a protocol attribute would have to match
    # exactly, so SqlCategories wouldn't count as Categories.
    @property
    def categories(self) -> Categories: ...

    @property
    def attribute_definitions(self) -> AttributeDefinitions: ...

    @property
    def parts(self) -> PartDefinitions: ...

    @property
    def pinouts(self) -> Pinouts: ...


class CatalogUnitOfWork(CatalogRepositories, UnitOfWork, Protocol):
    """The catalog's own transaction: its repositories, and the commit that keeps them."""


class PartStock(Protocol):
    """How much of a part is on hand, answered by bootstrap over inventory's `PartTotals`:
    catalog never imports inventory."""

    async def on_hand(self, workspace_id: WorkspaceId, part_id: PartDefinitionId) -> int:
        """The part's stock summed over its lots, its in-stock units included; zero for a part
        no lot holds."""
        ...


class PartUses(Protocol):
    """Which bills of materials name a part, answered by bootstrap over projects'
    `ListPartUses` (09's decision 13): catalog never imports projects."""

    async def of_part(
        self, workspace_id: WorkspaceId, part_id: PartDefinitionId, limit: int
    ) -> PartUsage:
        """The BOMs naming the part: the first `limit`, and how many in all."""
        ...
