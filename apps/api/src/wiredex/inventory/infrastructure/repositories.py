"""Inventory in PostgreSQL: one repository per port, each bound to one workspace.

Every query filters `workspace_id` itself, the first of ADR 0007's two gates, even though the
policies on these tables already hide another workspace's rows. Defence in depth: the filter
is what makes a query's scope readable, and it is what still holds if a connection ever runs
without the setting the policies read.

Reading the location tree is Postgres's job. `ancestors` is one recursive query, so the chain
above a location costs one round trip however deep it sits (requirement 10.1). The short-code
counter is one `INSERT ... ON CONFLICT ... RETURNING`, which serializes concurrent callers in
a workspace on the row lock so a number is handed out once (requirement 2.2).
"""

from collections.abc import AsyncIterator, Iterable, Sequence

from sqlalchemy import Row, Select, delete, func, literal, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from wiredex.inventory.application.ports import LotBalance, ShortCodeKind
from wiredex.inventory.domain.ledger import StockMovement
from wiredex.inventory.domain.location import Location
from wiredex.inventory.domain.lot import StockBalance, StockLot
from wiredex.inventory.domain.values import (
    LocationId,
    LocationName,
    PartId,
    Quantity,
    StockLotId,
    WorkspaceId,
)
from wiredex.inventory.infrastructure.orm import (
    locations,
    stock_balances,
    stock_lots,
    stock_movements,
)

# Escaped rather than passed through: someone searching for "L-00%" means the characters, not
# a wildcard. Trigram search is a substring match, so the pattern is `%code%`.
_LIKE_WILDCARDS = str.maketrans({"\\": "\\\\", "%": "\\%", "_": "\\_"})
_LIKE_ESCAPE = "\\"


class SqlLocations:
    def __init__(self, session: AsyncSession, workspace_id: WorkspaceId) -> None:
        self._session = session
        self._workspace_id = workspace_id

    async def add(self, location: Location) -> None:
        self._session.add(location)

    async def get(self, location_id: LocationId) -> Location | None:
        # Not session.get(), which reads by primary key alone: another workspace's id has to
        # come back as nothing found, never as a row.
        found = await self._session.execute(self._mine().where(locations.c.id == location_id))
        return found.scalar_one_or_none()

    async def all(self) -> list[Location]:
        found = await self._session.execute(self._mine())
        return list(found.scalars())

    async def ancestors(self, location_id: LocationId) -> list[Location]:
        """The chain above the location, root first, in one recursive query (10.1).

        `steps` counts the levels walked up, so ordering by it backwards puts the root first.
        The location itself is dropped from the result: only its ancestors are wanted.
        """
        chain = (
            select(locations, literal(0).label("steps"))
            .where(
                locations.c.id == location_id,
                locations.c.workspace_id == self._workspace_id,
            )
            .cte("chain", recursive=True)
        )
        above = locations.alias("above")
        chain = chain.union_all(
            select(above, chain.c.steps + 1).where(
                above.c.id == chain.c.parent_id,
                above.c.workspace_id == self._workspace_id,
            )
        )
        walked = aliased(Location, chain)
        found = await self._session.execute(
            select(walked).where(chain.c.id != location_id).order_by(chain.c.steps.desc())
        )
        return list(found.scalars())

    async def children_of(self, location_id: LocationId) -> list[Location]:
        found = await self._session.execute(
            self._mine().where(locations.c.parent_id == location_id)
        )
        return list(found.scalars())

    async def sibling_named(
        self, parent_id: LocationId | None, name: LocationName
    ) -> Location | None:
        # IS NULL among the roots, the Python side of NULLS NOT DISTINCT: two roots named Lab
        # are siblings, not unrelated rows (requirement 1.3).
        under = (
            locations.c.parent_id.is_(None)
            if parent_id is None
            else locations.c.parent_id == parent_id
        )
        found = await self._session.execute(self._mine().where(under, locations.c.name == name))
        return found.scalar_one_or_none()

    async def search(self, query: str) -> list[Location]:
        """Locations whose code contains the query, case-insensitively, over the trigram index.

        Reuses catalog's `pg_trgm` approach for names: an `ILIKE '%code%'` the GIN index on
        `code` answers. An empty query would match every code, so the caller only searches on
        a non-empty one; the wildcards in the query are escaped to characters.
        """
        found = await self._session.execute(
            self._mine().where(locations.c.code.ilike(_containing(query), escape=_LIKE_ESCAPE))
        )
        return list(found.scalars())

    async def has_lots(self, location_id: LocationId) -> bool:
        """Whether any lot sits in the location, which blocks a delete (requirement 1.10)."""
        found = await self._session.scalar(
            select(literal(True))
            .select_from(stock_lots)
            .where(
                stock_lots.c.workspace_id == self._workspace_id,
                stock_lots.c.location_id == location_id,
            )
            .limit(1)
        )
        return found is not None

    async def remove(self, location: Location) -> None:
        await self._session.delete(location)

    def _mine(self) -> Select[tuple[Location]]:
        return select(Location).where(locations.c.workspace_id == self._workspace_id)


class SqlLots:
    def __init__(self, session: AsyncSession, workspace_id: WorkspaceId) -> None:
        self._session = session
        self._workspace_id = workspace_id

    async def get(self, lot_id: StockLotId) -> StockLot | None:
        found = await self._session.execute(self._mine().where(stock_lots.c.id == lot_id))
        return found.scalar_one_or_none()

    async def for_part_at(self, part_id: PartId, location_id: LocationId) -> StockLot | None:
        """The lot of a (part, location) pair, or None before the first receive (3.1, 3.2)."""
        found = await self._session.execute(
            self._mine().where(
                stock_lots.c.part_id == part_id,
                stock_lots.c.location_id == location_id,
            )
        )
        return found.scalar_one_or_none()

    async def add(self, lot: StockLot) -> None:
        self._session.add(lot)

    def _mine(self) -> Select[tuple[StockLot]]:
        return select(StockLot).where(stock_lots.c.workspace_id == self._workspace_id)


class SqlLedger:
    """The append-only ledger: rows go in, nothing updates or deletes them (ADR 0002, 4.10)."""

    def __init__(self, session: AsyncSession, workspace_id: WorkspaceId) -> None:
        self._session = session
        self._workspace_id = workspace_id

    async def append(self, movement: StockMovement) -> None:
        # The lot a movement points at has no ORM relationship to it (the mapping declares
        # none), so the unit of work can't know to write the lot first. A flush settles any
        # pending lot before the movement's insert, so the foreign key is satisfied; it writes
        # nothing on its own — the transaction is still the caller's to commit.
        await self._session.flush()
        self._session.add(movement)

    async def movements_of(self, lot_id: StockLotId) -> list[StockMovement]:
        """A lot's rows in the order they happened, over the (workspace, lot, created_at) index."""
        found = await self._session.execute(
            self._mine()
            .where(stock_movements.c.lot_id == lot_id)
            .order_by(stock_movements.c.created_at, stock_movements.c.id)
        )
        return list(found.scalars())

    async def all(self) -> AsyncIterator[StockMovement]:
        """Every movement of the workspace in time order, streamed for a rebuild (5.2).

        Ordered by (created_at, id) so a lot's rows fold in the order they happened and two
        rows sharing a timestamp keep one stable order. Streamed, not loaded whole: a rebuild
        of a long-lived workspace shouldn't hold the ledger in memory.
        """
        result = await self._session.stream(
            self._mine().order_by(stock_movements.c.created_at, stock_movements.c.id)
        )
        async for movement in result.scalars():
            yield movement

    def _mine(self) -> Select[tuple[StockMovement]]:
        return select(StockMovement).where(stock_movements.c.workspace_id == self._workspace_id)


class SqlBalanceSheet:
    """The balance projection: one row per lot, optimistic on `version` (ADR 0002)."""

    def __init__(self, session: AsyncSession, workspace_id: WorkspaceId) -> None:
        self._session = session
        self._workspace_id = workspace_id

    async def get(self, lot_id: StockLotId) -> StockBalance | None:
        found = await self._session.execute(
            select(
                stock_balances.c.lot_id,
                stock_balances.c.on_hand,
                stock_balances.c.reserved,
                stock_balances.c.version,
            ).where(
                stock_balances.c.workspace_id == self._workspace_id,
                stock_balances.c.lot_id == lot_id,
            )
        )
        row = found.one_or_none()
        return None if row is None else _balance_of(row)

    async def put(self, balance: StockBalance) -> None:
        """Write a balance, optimistic on its `version`: a stale write touches no row (5.5).

        A lot's first balance has no row yet — it is inserted; a later balance updates the row
        whose stored version is one behind the balance's and bumps it. The two are told apart
        by whether a row exists, not by the version: a lot receives its first movement inside
        one transaction, so its first persisted balance already carries version 1, not 0.
        `available` is derived on the entity and written from its property by hand, which keeps
        the CHECK `available = on_hand - reserved` satisfied. Zero rows updated means a
        concurrent movement won the race; the use case reloads and retries, so this method
        neither raises nor reports the miss — the count is the use case's to read through the
        balance it reloads.
        """
        await self._session.flush()
        exists = await self._session.scalar(
            select(literal(True))
            .select_from(stock_balances)
            .where(
                stock_balances.c.workspace_id == self._workspace_id,
                stock_balances.c.lot_id == balance.lot_id,
            )
            .limit(1)
        )
        if exists is None:
            await self._session.execute(
                stock_balances.insert().values(
                    lot_id=balance.lot_id,
                    workspace_id=self._workspace_id,
                    on_hand=balance.on_hand,
                    reserved=balance.reserved,
                    available=int(balance.available),
                    version=balance.version,
                )
            )
            return
        await self._session.execute(
            stock_balances.update()
            .where(
                stock_balances.c.lot_id == balance.lot_id,
                stock_balances.c.workspace_id == self._workspace_id,
                stock_balances.c.version == balance.version - 1,
            )
            .values(
                on_hand=balance.on_hand,
                reserved=balance.reserved,
                available=int(balance.available),
                version=balance.version,
            )
        )

    async def totals_by_part(self, part_ids: Sequence[PartId]) -> dict[PartId, int]:
        """The total on_hand per part across its lots, one grouped query (7.1, 7.2).

        `stock_balances` joined to `stock_lots` on `lot_id`, summed by `part_id`, so the parts
        list never loads a balance per row. A part with no stock isn't in the result; the
        caller reads a missing part as zero.
        """
        if not part_ids:
            return {}
        rows = await self._session.execute(
            select(stock_lots.c.part_id, func.coalesce(func.sum(stock_balances.c.on_hand), 0))
            .select_from(
                stock_lots.join(stock_balances, stock_balances.c.lot_id == stock_lots.c.id)
            )
            .where(
                stock_lots.c.workspace_id == self._workspace_id,
                stock_lots.c.part_id.in_(part_ids),
            )
            .group_by(stock_lots.c.part_id)
        )
        return {PartId(part_id): int(total) for part_id, total in rows.tuples()}

    async def by_part(self, part_id: PartId) -> list[LotBalance]:
        """A part's on_hand broken down by location, each with its location (7.3).

        `stock_balances` joined through `stock_lots` to `locations`, so one query carries both
        the on_hand and the location it sits in. Ordered by the location code, a stable order
        the breakdown reads well in.
        """
        found = await self._session.execute(
            select(Location, stock_balances.c.on_hand)
            .select_from(
                stock_lots.join(stock_balances, stock_balances.c.lot_id == stock_lots.c.id).join(
                    locations, locations.c.id == stock_lots.c.location_id
                )
            )
            .where(
                stock_lots.c.workspace_id == self._workspace_id,
                stock_lots.c.part_id == part_id,
            )
            .order_by(locations.c.code)
        )
        return [
            LotBalance(location=location, on_hand=Quantity(int(on_hand)))
            for location, on_hand in found.tuples()
        ]

    async def replace_all(self, balances: Iterable[StockBalance]) -> None:
        """Replace the whole projection with these, for `wiredex stock rebuild` (5.2).

        The workspace's balances out and these in, in the caller's one transaction: a rebuild
        never leaves the projection half-written. The delete filters `workspace_id` itself, so
        it clears only this workspace's rows even before the policy narrows it. Each balance is
        inserted fresh with the version it was folded to, `available` set from its property so
        the CHECK holds.
        """
        await self._session.execute(
            delete(stock_balances).where(stock_balances.c.workspace_id == self._workspace_id)
        )
        rows = [
            {
                "lot_id": balance.lot_id,
                "workspace_id": self._workspace_id,
                "on_hand": balance.on_hand,
                "reserved": balance.reserved,
                "available": int(balance.available),
                "version": balance.version,
            }
            for balance in balances
        ]
        if rows:
            await self._session.execute(stock_balances.insert(), rows)


class SqlShortCodes:
    """The per-workspace short-code counter, one row per (workspace, kind).

    A global Postgres SEQUENCE can't give gap-free, per-workspace numbers (it is per database
    and leaves gaps), so the counter is a row and `next` bumps it with one
    `INSERT ... ON CONFLICT DO UPDATE ... RETURNING`. The row lock the conflict path takes
    serializes two concurrent receives in one workspace, so a number is handed out once
    (requirement 2.2). The advance rides in the use case's transaction: a rolled-back create
    doesn't burn a number.
    """

    def __init__(self, session: AsyncSession, workspace_id: WorkspaceId) -> None:
        self._session = session
        self._workspace_id = workspace_id

    async def next(self, kind: ShortCodeKind) -> int:
        """Advance the workspace's counter for a kind inside the transaction and return it (2.1).

        The first call inserts the row seeded at 2 and returns 1; every later call bumps
        `next_value` and returns the value it just consumed. The counter table has its own
        row-level security, so the write is scoped to this workspace like everything else.
        """
        result = await self._session.execute(
            text(
                "INSERT INTO short_code_counters (workspace_id, kind, next_value)"
                " VALUES (:workspace_id, :kind, 2)"
                " ON CONFLICT (workspace_id, kind)"
                " DO UPDATE SET next_value = short_code_counters.next_value + 1"
                " RETURNING next_value - 1"
            ),
            {"workspace_id": str(self._workspace_id), "kind": kind.value},
        )
        return int(result.scalar_one())


def _balance_of(row: Row[tuple[StockLotId, Quantity, Quantity, int]]) -> StockBalance:
    """One row as a balance. `on_hand` and `reserved` come back as `Quantity` already, through
    the column's `QuantityType`. `available` is derived, so it isn't read: the entity
    recomputes it, and the CHECK guaranteed the stored row agreed."""
    lot_id, on_hand, reserved, version = row
    return StockBalance(lot_id=lot_id, on_hand=on_hand, reserved=reserved, version=version)


def _containing(text_value: str) -> str:
    return f"%{text_value.translate(_LIKE_WILDCARDS)}%"
