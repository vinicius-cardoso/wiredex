"""The catalog in PostgreSQL: one repository per port, each bound to one workspace.

Every query filters `workspace_id` itself, the first of ADR 0007's two gates, even though
the policies on these tables would already hide another workspace's rows. Defence in
depth: the filter is what makes a query's scope readable, and it is what still holds if a
connection ever runs without the setting the policies read.

Reading the tree is Postgres's job. `ancestors` is one recursive query, so resolving a
category's schema costs one round trip however deep it sits (requirement 8.1).
"""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import (
    ColumnElement,
    RowMapping,
    Select,
    and_,
    delete,
    func,
    insert,
    literal,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from wiredex.catalog.application.ports import Page, PartQuery
from wiredex.catalog.application.search import Facets
from wiredex.catalog.domain.category import MAX_CATEGORY_DEPTH, Category
from wiredex.catalog.domain.part import PartDefinition
from wiredex.catalog.domain.pinout import (
    Pin,
    PinFunction,
    PinLabel,
    PinNumber,
    Pinout,
    PinType,
    VoltageLevel,
)
from wiredex.catalog.domain.schema import AttributeDefinition, AttributeSchema
from wiredex.catalog.domain.search import PartSort, SearchCursor, Spec
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
    pins,
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

    async def descendants(self, category_id: CategoryId) -> list[CategoryId]:
        """The category and every one under it, ids alone, in one recursive query.

        The mirror of `ancestors`, walking down instead of up: the seed is the category
        itself (so it is included, which is what `InCategories` filters on), and each step
        takes the children of a row already in the tree. Both the seed and the step filter
        `workspace_id` themselves (ADR 0007's first gate), so another workspace's tree stays
        unseen even were a child's parent id to collide.
        """
        tree = (
            select(categories.c.id)
            .where(
                categories.c.id == category_id,
                categories.c.workspace_id == self._workspace_id,
            )
            .cte("tree", recursive=True)
        )
        below = categories.alias("below")
        tree = tree.union_all(
            select(below.c.id).where(
                below.c.parent_id == tree.c.id,
                below.c.workspace_id == self._workspace_id,
            )
        )
        found = await self._session.execute(select(tree.c.id))
        return [CategoryId(found_id) for found_id in found.scalars()]

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

    async def remove_all(self) -> None:
        """The whole tree, a level at a time, the leaves first.

        `parent_id` is ON DELETE RESTRICT and Postgres checks it there and then, so a parent
        deleted in the same statement as its children is refused. Each statement takes the
        childless rows, which is one level; the depth cap says how many levels there can be,
        so that many statements clear any tree, and the last ones find nothing left.
        """
        children = categories.alias("children")
        leaves = delete(categories).where(
            categories.c.workspace_id == self._workspace_id,
            ~select(literal(1))
            .where(children.c.parent_id == categories.c.id)
            .correlate(categories)
            .exists(),
        )
        for _ in range(MAX_CATEGORY_DEPTH):
            await self._session.execute(leaves)

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

    async def remove_all(self) -> None:
        await self._session.execute(
            delete(attribute_definitions).where(
                attribute_definitions.c.workspace_id == self._workspace_id
            )
        )

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

    async def search(
        self, spec: Spec, sort: PartSort, after: SearchCursor | None, limit: int
    ) -> Page[PartDefinition, SearchCursor]:  # pragma: no cover
        # Compiling the spec to one SQL query, with the sort, NULLS LAST, the id tie-break
        # and the keyset from the cursor, lands in task 6 with its integration and property
        # tests. The port declares it now so the search use case (task 3) has a seam to call.
        raise NotImplementedError("SqlPartDefinitions.search: implemented in task 6")

    async def facets(self, spec: Spec, schema: AttributeSchema) -> Facets:  # pragma: no cover
        # The grouped facet queries land in task 7. Declared now for the same reason.
        raise NotImplementedError("SqlPartDefinitions.facets: implemented in task 7")

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

    async def remove_all(self) -> None:
        await self._session.execute(
            delete(part_definitions).where(part_definitions.c.workspace_id == self._workspace_id)
        )

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


class SqlPinouts:
    """A part's pins as rows, with Core and no mapping: a pin has no identity of its own.

    The other three repositories hand SQLAlchemy an entity and let the session work out the
    statements. Here the repository is the mapping: it reads rows into a `Pinout` and writes a
    `Pinout` back as rows, which is what keeps `pins` out of the domain (design §2).

    The cost is fixed, whatever the pin count: one `SELECT` to read a table (requirement 7.1),
    one `DELETE` and one `INSERT` of every row to replace it (requirement 7.2). `workspace_id`
    is in all three, ADR 0007's first gate, next to the policy that already hides the rest.
    """

    def __init__(self, session: AsyncSession, workspace_id: WorkspaceId) -> None:
        self._session = session
        self._workspace_id = workspace_id

    async def of_part(self, part_id: PartDefinitionId) -> Pinout:
        """The part's pins in the order they were saved, in one query (requirement 7.1)."""
        found = await self._session.execute(
            select(pins.c.number, pins.c.label, pins.c.type, pins.c.functions, pins.c.voltage)
            .where(self._of(part_id))
            .order_by(pins.c.position)
        )
        # Through the collection, not around it: a pinout read from the database is built by
        # the same code a client's rows are, so neither can hold what the other would refuse.
        return Pinout(_pin_of(row) for row in found.mappings())

    async def replace(self, part_id: PartDefinitionId, pinout: Pinout) -> None:
        """The old rows out and these in, in two statements and never one per pin (7.2).

        Both in the caller's transaction, so a pinout is never stored half-replaced
        (requirement 1.3): the `DELETE` is only real once the unit of work commits.

        The flush is what mapping by hand costs: a Core statement doesn't autoflush, as an
        ORM one does, so a part added in this same unit of work would still be pending and the
        composite foreign key would refuse its pins. It writes nothing on its own — the
        transaction is still the caller's to commit — and finds nothing to do on the usual
        path, where the part was read from the database to begin with.
        """
        await self._session.flush()
        await self._session.execute(delete(pins).where(self._of(part_id)))
        rows = [self._row_of(part_id, position, pin) for position, pin in enumerate(pinout)]
        if rows:
            # One statement carrying every row, which is what an empty pinout doesn't need:
            # clearing a table is the DELETE above and nothing else (requirement 1.4).
            await self._session.execute(insert(pins), rows)

    async def count_of(self, part_id: PartDefinitionId) -> int:
        """How many pins the part has, for a part page that shouldn't read them all (1.8)."""
        counted = await self._session.scalar(
            select(func.count()).select_from(pins).where(self._of(part_id))
        )
        return counted or 0

    def _of(self, part_id: PartDefinitionId) -> ColumnElement[bool]:
        """One part's rows, named the same way in every statement: the workspace, then the part."""
        return and_(pins.c.workspace_id == self._workspace_id, pins.c.part_id == part_id)

    def _row_of(self, part_id: PartDefinitionId, position: int, pin: Pin) -> dict[str, Any]:
        """One pin as its row. `position` is the order the table was saved in, 0-based."""
        return {
            "workspace_id": self._workspace_id,
            "part_id": part_id,
            "position": position,
            "number": pin.number.value,
            "label": pin.label.value,
            "type": pin.type,
            "functions": [function.value for function in pin.functions],
            # The exact Decimal into a numeric column: no float gets to round 3.3 on the way.
            "voltage": None if pin.voltage is None else pin.voltage.value,
        }


def _pin_of(row: RowMapping) -> Pin:
    """One row as a pin, every cell back through the value object that validated it."""
    return Pin(
        PinNumber(row["number"]),
        PinLabel(row["label"]),
        PinType(row["type"]),
        tuple(PinFunction(function) for function in row["functions"]),
        None if row["voltage"] is None else VoltageLevel(row["voltage"]),
    )


def _containing(text: str) -> str:
    return f"%{text.translate(_LIKE_WILDCARDS)}%"


def _folded(manufacturer: Manufacturer | None) -> str:
    # coalesce(manufacturer, '') on the Python side, so a part with no manufacturer is
    # compared as the empty string and two bare MPNs still collide (design §5).
    return "" if manufacturer is None else manufacturer.value.lower()
