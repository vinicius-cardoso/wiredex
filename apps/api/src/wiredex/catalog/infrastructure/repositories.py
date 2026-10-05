"""The catalog in PostgreSQL: one repository per port, each bound to one workspace.

Every query filters `workspace_id` itself, the first of ADR 0007's two gates, even though
the policies on these tables would already hide another workspace's rows. Defence in
depth: the filter is what makes a query's scope readable, and it is what still holds if a
connection ever runs without the setting the policies read.

Reading the tree is Postgres's job. `ancestors` is one recursive query, so resolving a
category's schema costs one round trip however deep it sits (requirement 8.1).
"""

import typing
from collections.abc import Sequence
from typing import Any

from sqlalchemy import (
    ColumnElement,
    RowMapping,
    Select,
    and_,
    cast,
    delete,
    func,
    insert,
    literal,
    or_,
    select,
)
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import UnaryExpression
from sqlalchemy.types import Text

from wiredex.catalog.application.ports import PartQuery
from wiredex.catalog.application.search import BoolCounts, Facets, NumberRange
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
from wiredex.catalog.domain.search import PartSort, SortDirection, SortField, Spec
from wiredex.catalog.domain.values import (
    AttributeDefinitionId,
    AttributeKind,
    CategoryId,
    CategoryName,
    Manufacturer,
    Mpn,
    PartDefinitionId,
    SiValue,
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
from wiredex.catalog.infrastructure.search_sql import (
    attribute_is_string,
    attribute_text,
    compile_spec,
    contains_bool,
    number_value,
)
from wiredex.shared_kernel.domain.paging import PageRequest
from wiredex.shared_kernel.domain.trash import TrashedSlice
from wiredex.shared_kernel.infrastructure.trash import in_the_trash, live, sliced, trash_newest

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

    async def find(self, text: str, limit: int) -> list[Category]:
        found = await self._session.execute(
            self._mine()
            .where(categories.c.name.ilike(_containing(text), escape=_LIKE_ESCAPE))
            .order_by(*_starting_first(categories.c.name, text), categories.c.id)
            .limit(limit)
        )
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

    async def locked(self, part_id: PartDefinitionId) -> PartDefinition | None:
        """The live part, its row locked until the transaction ends (16's decision 3).

        `trashed_at IS NULL` is in the `WHERE`, so a request that queued behind a move to the
        trash gets nothing once it holds the lock: Postgres checks the condition again against
        the row that move committed.
        """
        found = await self._session.execute(
            self._mine()
            .where(part_definitions.c.id == part_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return found.scalar_one_or_none()

    async def find(self, text: str, limit: int) -> list[PartDefinition]:
        pattern = _containing(text)
        found = await self._session.execute(
            self._mine()
            .where(
                or_(
                    part_definitions.c.name.ilike(pattern, escape=_LIKE_ESCAPE),
                    part_definitions.c.mpn.ilike(pattern, escape=_LIKE_ESCAPE),
                    part_definitions.c.manufacturer.ilike(pattern, escape=_LIKE_ESCAPE),
                )
            )
            .order_by(*_starting_first(part_definitions.c.name, text), part_definitions.c.id)
            .limit(limit)
        )
        return list(found.scalars())

    async def with_ids(self, part_ids: Sequence[PartDefinitionId]) -> list[PartDefinition]:
        # One `IN`, whatever the number of ids: a BOM of thirty parts is one statement.
        found = await self._session.execute(self._mine().where(part_definitions.c.id.in_(part_ids)))
        return list(found.scalars())

    async def count_listed(self, query: PartQuery) -> int:
        counted = await self._session.scalar(
            select(func.count()).select_from(part_definitions).where(*self._listed_by(query))
        )
        return counted or 0

    async def listed(self, query: PartQuery, page: PageRequest) -> list[PartDefinition]:
        """One page of the list, ordered by id, which for UUIDv7 is by when it was defined;
        the id is unique, so the order is total and pages neither repeat nor skip."""
        found = await self._session.execute(
            select(PartDefinition)
            .where(*self._listed_by(query))
            .order_by(part_definitions.c.id)
            .offset(page.offset)
            .limit(page.size)
        )
        return list(found.scalars())

    async def count_matching(self, spec: Spec) -> int:
        counted = await self._session.scalar(
            select(func.count()).select_from(part_definitions).where(self._matching(spec))
        )
        return counted or 0

    async def search(self, spec: Spec, sort: PartSort, page: PageRequest) -> list[PartDefinition]:
        """One page of the parts the spec matches, in the sort's order, in one query.

        The spec compiles to one predicate (`compile_spec`), the same one `count_matching`
        counts with, whatever the filter count (requirement 7.3); the sort to an `ORDER BY`
        with parts missing the sort value last and the id breaking ties, a total order, so
        OFFSET/LIMIT pages neither repeat nor skip a part.
        """
        found = await self._session.execute(
            select(PartDefinition)
            .where(self._matching(spec))
            .order_by(*_ordering(sort, _sort_value(sort)))
            .offset(page.offset)
            .limit(page.size)
        )
        return list(found.scalars())

    async def facets(self, spec: Spec, schema: AttributeSchema) -> Facets:
        """What the matching parts hold, per attribute of the schema, one query per kind.

        The mirror of the fake's `facets` (tests/support/catalog.py): the spec narrows the
        parts to count over — category, text and pin, since the application keeps the
        attribute filters out (requirement 5.2) — and each kind is aggregated over that same
        set. Enum options are counted grouped by value, booleans by JSON containment, numbers
        by the min and max of the guarded numeric value; a number attribute no part has a
        value for gets `None` (requirement 5.3). All three run over the workspace filter and
        the compiled spec, the keys always bound.
        """
        over = self._matching(spec)
        facets = Facets()
        by_kind: dict[AttributeKind, list[AttributeDefinition]] = {}
        for definition in schema:
            by_kind.setdefault(definition.kind, []).append(definition)
        for definition in by_kind.get(AttributeKind.ENUM, ()):
            facets.enums[definition.key] = await self._enum_counts(over, definition)
        for definition in by_kind.get(AttributeKind.BOOL, ()):
            facets.bools[definition.key] = await self._bool_counts(over, definition)
        for definition in by_kind.get(AttributeKind.NUMBER, ()):
            facets.numbers[definition.key] = await self._number_range(over, definition)
        return facets

    async def _enum_counts(
        self, over: ColumnElement[bool], definition: AttributeDefinition
    ) -> dict[str, int]:
        """Each declared option and how many matching parts hold it; an option nobody has is 0.

        Grouped by the string value under the key (a wrong-kind value isn't a JSON string and
        drops out, as the fake's `isinstance(value, str)` does), then the declared options are
        filled in so an option no part holds still answers zero.
        """
        value = attribute_text(definition.key)
        rows = await self._session.execute(
            select(value, func.count())
            .select_from(part_definitions)
            .where(over, attribute_is_string(definition.key))
            .group_by(value)
        )
        held = {str(option): counted for option, counted in rows.tuples()}
        return {option: held.get(option, 0) for option in definition.options}

    async def _bool_counts(
        self, over: ColumnElement[bool], definition: AttributeDefinition
    ) -> BoolCounts:
        """How many matching parts hold true and how many hold false, by JSON containment.

        `@>` compares the JSON boolean, so a stored number or string under the key counts as
        neither — the same answer the fake's `is True` / `is False` gives. Two filtered counts
        in one query, so a boolean facet is one round trip.
        """
        counts = await self._session.execute(
            select(
                func.count().filter(contains_bool(definition.key, value=True)),
                func.count().filter(contains_bool(definition.key, value=False)),
            )
            .select_from(part_definitions)
            .where(over)
        )
        true_count, false_count = counts.one()
        return BoolCounts(true=true_count, false=false_count)

    async def _number_range(
        self, over: ColumnElement[bool], definition: AttributeDefinition
    ) -> NumberRange | None:
        """The lowest and highest number a matching part holds, or `None` when none does.

        `number_value` is NULL for a missing or wrong-kind value, so `min` and `max` ignore
        those, and both come back NULL when no part has a number — which is the `None` range
        (requirement 5.3).
        """
        number = number_value(definition.key)
        bounds = await self._session.execute(
            select(func.min(number), func.max(number)).select_from(part_definitions).where(over)
        )
        low, high = bounds.one()
        if low is None or high is None:
            return None
        return NumberRange(SiValue(low), SiValue(high))

    async def with_mpn(self, manufacturer: Manufacturer | None, mpn: Mpn) -> PartDefinition | None:
        # Any part, in the trash or not: the unique index holds both (16's decision 5).
        found = await self._session.execute(
            self._any().where(
                folded_manufacturer == _folded(manufacturer),
                folded_mpn == mpn.fold(),
            )
        )
        return found.scalar_one_or_none()

    async def count_in(self, category_ids: Sequence[CategoryId]) -> int:
        return await self._count_in(category_ids, live(part_definitions))

    async def count_in_trash(self, category_ids: Sequence[CategoryId]) -> int:
        return await self._count_in(category_ids, in_the_trash(part_definitions))

    async def counts_by_category(self) -> dict[CategoryId, int]:
        """One grouped query, because the tree asks for every category at once (1.11). Live
        parts only: the tree counts what its pages list."""
        rows = await self._session.execute(
            select(part_definitions.c.category_id, func.count())
            .where(
                part_definitions.c.workspace_id == self._workspace_id,
                live(part_definitions),
            )
            .group_by(part_definitions.c.category_id)
        )
        return {CategoryId(category_id): counted for category_id, counted in rows.tuples()}

    async def remove(self, part: PartDefinition) -> None:
        await self._session.delete(part)

    async def remove_all(self) -> None:
        await self._session.execute(
            delete(part_definitions).where(part_definitions.c.workspace_id == self._workspace_id)
        )

    async def trashed(self, count: int, text: str | None) -> TrashedSlice[PartDefinition]:
        """The newest of the trash and their total in one statement, over
        `ix_part_definitions_trashed` (16's decision 9)."""
        statement = self._any()
        if text is not None:
            pattern = _containing(text)
            statement = statement.where(
                or_(
                    part_definitions.c.name.ilike(pattern, escape=_LIKE_ESCAPE),
                    part_definitions.c.mpn.ilike(pattern, escape=_LIKE_ESCAPE),
                )
            )
        found = await self._session.execute(trash_newest(statement, part_definitions, count))
        return sliced(found.tuples())

    async def ids_named(self, text: str) -> frozenset[PartDefinitionId]:
        found = await self._session.scalars(
            select(part_definitions.c.id).where(
                part_definitions.c.workspace_id == self._workspace_id,
                live(part_definitions),
                part_definitions.c.name.ilike(_containing(text), escape=_LIKE_ESCAPE),
            )
        )
        return frozenset(PartDefinitionId(part_id) for part_id in found)

    async def in_trash(self, part_id: PartDefinitionId) -> PartDefinition | None:
        """Locked and fresh, so a restore and a delete for good of one part take turns, and the
        second finds nothing (16's decision 10)."""
        found = await self._session.execute(
            self._any()
            .where(part_definitions.c.id == part_id, in_the_trash(part_definitions))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return found.scalar_one_or_none()

    async def empty_trash(self) -> int:
        """One `DELETE`; each row it takes is locked and checked again, so a restore racing it
        either wins or finds nothing. The pins go by the key's cascade."""
        result = await self._session.execute(
            delete(part_definitions).where(
                part_definitions.c.workspace_id == self._workspace_id,
                in_the_trash(part_definitions),
            )
        )
        return typing.cast("CursorResult[Any]", result).rowcount

    async def kept(self, part_id: PartDefinitionId) -> bool:
        found = await self._session.scalar(
            select(literal(True))
            .select_from(part_definitions)
            .where(
                part_definitions.c.workspace_id == self._workspace_id,
                part_definitions.c.id == part_id,
            )
        )
        return found is not None

    async def _count_in(
        self, category_ids: Sequence[CategoryId], state: ColumnElement[bool]
    ) -> int:
        counted = await self._session.scalar(
            select(func.count())
            .select_from(part_definitions)
            .where(
                part_definitions.c.workspace_id == self._workspace_id,
                part_definitions.c.category_id.in_(category_ids),
                state,
            )
        )
        return counted or 0

    def _listed_by(self, query: PartQuery) -> list[ColumnElement[bool]]:
        """The plain list's filters, shared by its count and its rows: the workspace's live
        parts, narrowed by category and by a substring of the name."""
        where = [part_definitions.c.workspace_id == self._workspace_id, live(part_definitions)]
        if query.category_id is not None:
            where.append(part_definitions.c.category_id == query.category_id)
        if query.text is not None:
            where.append(
                part_definitions.c.name.ilike(_containing(query.text), escape=_LIKE_ESCAPE)
            )
        return where

    def _matching(self, spec: Spec) -> ColumnElement[bool]:
        """A search's filters, shared by its count and its rows: the workspace's live parts
        the compiled spec matches."""
        return and_(
            part_definitions.c.workspace_id == self._workspace_id,
            live(part_definitions),
            compile_spec(spec),
        )

    def _mine(self) -> Select[tuple[PartDefinition]]:
        """The workspace's live parts: every read but the trash's own, and the MPN check, goes
        through here, so a part in the trash is absent everywhere (16's decision 2)."""
        return self._any().where(live(part_definitions))

    def _any(self) -> Select[tuple[PartDefinition]]:
        """The workspace's parts, in the trash or not."""
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

    async def of_parts(
        self, part_ids: Sequence[PartDefinitionId]
    ) -> dict[PartDefinitionId, Pinout]:
        """Several parts' pins in one query, grouped into pinouts in their saved order: what a
        netlist reads for every part on a BOM at once (11-netlist-editor requirement 7.3)."""
        if not part_ids:
            return {}
        found = await self._session.execute(
            select(
                pins.c.part_id,
                pins.c.number,
                pins.c.label,
                pins.c.type,
                pins.c.functions,
                pins.c.voltage,
            )
            .where(pins.c.workspace_id == self._workspace_id, pins.c.part_id.in_(part_ids))
            .order_by(pins.c.part_id, pins.c.position)
        )
        grouped: dict[PartDefinitionId, list[Pin]] = {}
        for row in found.mappings():
            grouped.setdefault(PartDefinitionId(row["part_id"]), []).append(_pin_of(row))
        return {part_id: Pinout(rows) for part_id, rows in grouped.items()}

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


# --- Search ordering --------------------------------------------------------------------
#
# The SQL half of what the in-memory fake does in Python (tests/support/catalog.py): the sort
# value per field and the ORDER BY with nulls last and the id tie-break. The two are kept
# deliberately identical, because a property test pages the same search through both and the
# ids — and their order — have to match.


def _sort_value(sort: PartSort) -> ColumnElement[Any]:
    """What a part is ordered by under this sort: the id, the folded name, or the number.

    An attribute sort's value is NULL for a part with no number under the key, which is what
    sorts it last. Newest orders by id (UUIDv7 is creation order) and name by the folded name,
    neither ever missing, so only an attribute sort ever yields NULL.
    """
    if sort.field is SortField.NEWEST:
        # `id` cast to text, as the fake orders by `str(id)`; UUIDv7 hex sorts the same as the
        # uuid, so the order is unchanged.
        return cast(part_definitions.c.id, Text)
    if sort.field is SortField.NAME:
        # The folded name as plain text, the value the fake orders by too.
        return cast(func.lower(cast(part_definitions.c.name, Text)), Text)
    assert sort.key is not None  # noqa: S101  an attribute sort always carries its key
    # The number the attribute filter reads too: NULL for a missing or wrong-kind value, which
    # is what sorts such a part last (requirement 2.7).
    return number_value(sort.key)


def _ordering(sort: PartSort, value: ColumnElement[Any]) -> list[UnaryExpression[Any]]:
    """The ORDER BY: the value in the sort direction with nulls last, then the id ascending.

    The id tie-break is always ascending, whatever the value direction, so two parts sharing a
    sort value keep one stable order and a page neither repeats nor skips one of them
    (requirement 4.3); parts without the value come last in either direction (requirement 4.2).
    """
    if sort.direction is SortDirection.DESC:
        primary = value.desc().nulls_last()
    else:
        primary = value.asc().nulls_last()
    return [primary, part_definitions.c.id.asc()]


def _containing(text: str) -> str:
    return f"%{text.translate(_LIKE_WILDCARDS)}%"


def _starting_first(title: ColumnElement[Any], text: str) -> tuple[ColumnElement[Any], ...]:
    """A find's order (19-command-palette, decision 2): the titles starting with the text
    first, then the rest, each by the title folded. `COLLATE "C"` orders by code point, as
    Python's sort does, whatever collation the database was created with."""
    starting = f"{text.translate(_LIKE_WILDCARDS)}%"
    return (
        title.ilike(starting, escape=_LIKE_ESCAPE).desc(),
        func.lower(title).collate("C"),
    )


def _folded(manufacturer: Manufacturer | None) -> str:
    # coalesce(manufacturer, '') on the Python side, so a part with no manufacturer is
    # compared as the empty string and two bare MPNs still collide (design §5).
    return "" if manufacturer is None else manufacturer.value.lower()
