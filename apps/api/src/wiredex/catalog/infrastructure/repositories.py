"""The catalog in PostgreSQL: one repository per port, each bound to one workspace.

Every query filters `workspace_id` itself, the first of ADR 0007's two gates, even though
the policies on these tables would already hide another workspace's rows. Defence in
depth: the filter is what makes a query's scope readable, and it is what still holds if a
connection ever runs without the setting the policies read.

Reading the tree is Postgres's job. `ancestors` is one recursive query, so resolving a
category's schema costs one round trip however deep it sits (requirement 8.1).
"""

from collections.abc import Sequence

from sqlalchemy import Select, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from wiredex.catalog.application.ports import Page, PartQuery
from wiredex.catalog.domain.category import Category
from wiredex.catalog.domain.part import PartDefinition
from wiredex.catalog.domain.schema import AttributeDefinition
from wiredex.catalog.domain.values import (
    AttributeDefinitionId,
    CategoryId,
    CategoryName,
    Manufacturer,
    Mpn,
    PartDefinitionId,
    WorkspaceId,
)
from wiredex.catalog.infrastructure.orm import (
    attribute_definitions,
    categories,
    folded_manufacturer,
    folded_mpn,
    part_definitions,
)

# Escaped rather than passed through: someone searching for "100%" means the characters,
# not every part in the workspace.
_LIKE_WILDCARDS = str.maketrans({"\\": "\\\\", "%": "\\%", "_": "\\_"})
_LIKE_ESCAPE = "\\"


class SqlCategories:
    def __init__(self, session: AsyncSession, workspace_id: WorkspaceId) -> None:
        self._session = session
        self._workspace_id = workspace_id

    async def add(self, category: Category) -> None:
        self._session.add(category)

    async def get(self, category_id: CategoryId) -> Category | None:
        # Not session.get(), which reads by primary key alone: another workspace's id has
        # to come back as nothing found, never as a row (requirement 6.4).
        found = await self._session.execute(self._mine().where(categories.c.id == category_id))
        return found.scalar_one_or_none()

    async def all(self) -> list[Category]:
        found = await self._session.execute(self._mine())
        return list(found.scalars())

    async def ancestors(self, category_id: CategoryId) -> list[Category]:
        """The chain above the category, root first, in one recursive query.

        `steps` counts the levels walked up, so ordering by it backwards puts the root
        first — the order a schema resolves in, nearest ancestor last.
        """
        chain = (
            select(categories, literal(0).label("steps"))
            .where(
                categories.c.id == category_id,
                categories.c.workspace_id == self._workspace_id,
            )
            .cte("chain", recursive=True)
        )
        above = categories.alias("above")
        chain = chain.union_all(
            select(above, chain.c.steps + 1).where(
                above.c.id == chain.c.parent_id,
                above.c.workspace_id == self._workspace_id,
            )
        )
        walked = aliased(Category, chain)
        found = await self._session.execute(
            select(walked).where(chain.c.id != category_id).order_by(chain.c.steps.desc())
        )
        return list(found.scalars())

    async def children_of(self, category_id: CategoryId) -> list[Category]:
        found = await self._session.execute(
            self._mine().where(categories.c.parent_id == category_id)
        )
        return list(found.scalars())

    async def sibling_named(
        self, parent_id: CategoryId | None, name: CategoryName
    ) -> Category | None:
        # IS NULL among the roots, which is the Python side of NULLS NOT DISTINCT: two
        # roots named Passives are siblings, not unrelated rows (requirement 1.3).
        under = (
            categories.c.parent_id.is_(None)
            if parent_id is None
            else categories.c.parent_id == parent_id
        )
        found = await self._session.execute(self._mine().where(under, categories.c.name == name))
        return found.scalar_one_or_none()

    async def remove(self, category: Category) -> None:
        await self._session.delete(category)

    def _mine(self) -> Select[tuple[Category]]:
        return select(Category).where(categories.c.workspace_id == self._workspace_id)


class SqlAttributeDefinitions:
    def __init__(self, session: AsyncSession, workspace_id: WorkspaceId) -> None:
        self._session = session
        self._workspace_id = workspace_id

    async def add(self, definition: AttributeDefinition) -> None:
        self._session.add(definition)

    async def get(self, definition_id: AttributeDefinitionId) -> AttributeDefinition | None:
        found = await self._session.execute(
            self._mine().where(attribute_definitions.c.id == definition_id)
        )
        return found.scalar_one_or_none()

    async def of_categories(self, category_ids: Sequence[CategoryId]) -> list[AttributeDefinition]:
        found = await self._session.execute(
            self._mine()
            .where(attribute_definitions.c.category_id.in_(category_ids))
            # The schema orders each category's own group again; coming out of the database
            # in form order keeps two definitions sharing a position in one stable order.
            .order_by(attribute_definitions.c.position, attribute_definitions.c.key)
        )
        return list(found.scalars())

    async def remove(self, definition: AttributeDefinition) -> None:
        await self._session.delete(definition)

    def _mine(self) -> Select[tuple[AttributeDefinition]]:
        return select(AttributeDefinition).where(
            attribute_definitions.c.workspace_id == self._workspace_id
        )


class SqlPartDefinitions:
    def __init__(self, session: AsyncSession, workspace_id: WorkspaceId) -> None:
        self._session = session
        self._workspace_id = workspace_id

    async def add(self, part: PartDefinition) -> None:
        self._session.add(part)

    async def get(self, part_id: PartDefinitionId) -> PartDefinition | None:
        found = await self._session.execute(self._mine().where(part_definitions.c.id == part_id))
        return found.scalar_one_or_none()

    async def page(self, query: PartQuery) -> Page[PartDefinition]:
        """One window of the list, ordered by id, which for UUIDv7 is by when it was defined.

        A keyset page, not an offset one: the cursor is the last id of the window, so a part
        defined meanwhile can't shift the next page (requirement 4.11).
        """
        found = await self._session.execute(self._window(query))
        rows = list(found.scalars())
        window = tuple(rows[: query.limit])
        # One row more than asked for is how the page knows there is a next one.
        more = len(rows) > len(window)
        return Page(window, window[-1].id if more and window else None)

    async def with_mpn(self, manufacturer: Manufacturer | None, mpn: Mpn) -> PartDefinition | None:
        found = await self._session.execute(
            self._mine().where(
                folded_manufacturer == _folded(manufacturer),
                folded_mpn == mpn.fold(),
            )
        )
        return found.scalar_one_or_none()

    async def count_in(self, category_ids: Sequence[CategoryId]) -> int:
        counted = await self._session.scalar(
            select(func.count())
            .select_from(part_definitions)
            .where(
                part_definitions.c.workspace_id == self._workspace_id,
                part_definitions.c.category_id.in_(category_ids),
            )
        )
        return counted or 0

    async def counts_by_category(self) -> dict[CategoryId, int]:
        """One grouped query, because the tree asks for every category at once (1.11)."""
        rows = await self._session.execute(
            select(part_definitions.c.category_id, func.count())
            .where(part_definitions.c.workspace_id == self._workspace_id)
            .group_by(part_definitions.c.category_id)
        )
        return {CategoryId(category_id): counted for category_id, counted in rows.tuples()}

    async def remove(self, part: PartDefinition) -> None:
        await self._session.delete(part)

    def _window(self, query: PartQuery) -> Select[tuple[PartDefinition]]:
        # One row over the limit: reading it is what says whether a next page exists.
        statement = self._mine().order_by(part_definitions.c.id).limit(query.limit + 1)
        if query.category_id is not None:
            statement = statement.where(part_definitions.c.category_id == query.category_id)
        if query.text is not None:
            statement = statement.where(
                part_definitions.c.name.ilike(_containing(query.text), escape=_LIKE_ESCAPE)
            )
        if query.after is not None:
            statement = statement.where(part_definitions.c.id > query.after)
        return statement

    def _mine(self) -> Select[tuple[PartDefinition]]:
        return select(PartDefinition).where(part_definitions.c.workspace_id == self._workspace_id)


def _containing(text: str) -> str:
    return f"%{text.translate(_LIKE_WILDCARDS)}%"


def _folded(manufacturer: Manufacturer | None) -> str:
    # coalesce(manufacturer, '') on the Python side, so a part with no manufacturer is
    # compared as the empty string and two bare MPNs still collide (design §5).
    return "" if manufacturer is None else manufacturer.value.lower()
