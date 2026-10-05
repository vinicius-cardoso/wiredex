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

from collections.abc import AsyncIterator, Collection, Iterable, Mapping, Sequence
from typing import Any, cast

from sqlalchemy import ColumnElement, Row, Select, Uuid, any_, delete, func, literal, select, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from wiredex.inventory.application.ports import (
    LockedLot,
    LotBalance,
    LotHolding,
    RevisionUnitRow,
    ShortCodeKind,
    UnitQuery,
)
from wiredex.inventory.domain.errors import ConcurrentStockError
from wiredex.inventory.domain.holdings import MovementSum
from wiredex.inventory.domain.ledger import StockMovement
from wiredex.inventory.domain.location import Location
from wiredex.inventory.domain.lot import StockBalance, StockLot
from wiredex.inventory.domain.unit import Unit, UnitStatus
from wiredex.inventory.domain.values import (
    LocationId,
    LocationName,
    Mac,
    MovementKind,
    PartId,
    Quantity,
    RevisionId,
    Serial,
    StockLotId,
    UnitId,
    WorkspaceId,
)
from wiredex.inventory.infrastructure.orm import (
    locations,
    stock_balances,
    stock_lots,
    stock_movements,
    units,
)
from wiredex.shared_kernel.domain.trash import TrashedSlice
from wiredex.shared_kernel.infrastructure.trash import in_the_trash, live, sliced, trash_newest

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

    async def find(self, text: str, limit: int) -> list[Location]:
        pattern = _containing(text)
        found = await self._session.execute(
            self._mine()
            .where(
                locations.c.name.ilike(pattern, escape=_LIKE_ESCAPE)
                | locations.c.code.ilike(pattern, escape=_LIKE_ESCAPE)
            )
            .order_by(*_starting_first(locations.c.name, text), locations.c.id)
            .limit(limit)
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

    async def lot_counts(self) -> Mapping[LocationId, int]:
        rows = await self._session.execute(
            select(stock_lots.c.location_id, func.count())
            .where(stock_lots.c.workspace_id == self._workspace_id)
            .group_by(stock_lots.c.location_id)
        )
        return {LocationId(location_id): count for location_id, count in rows.tuples()}

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

    async def at(
        self, location_id: LocationId, part_ids: Sequence[PartId]
    ) -> dict[PartId, StockLot]:
        """Each part's lot at the location, for the parts that have one, in one query (6.2)."""
        if not part_ids:
            return {}
        found = await self._session.execute(
            self._mine().where(
                stock_lots.c.location_id == location_id,
                stock_lots.c.part_id.in_(part_ids),
            )
        )
        return {PartId(lot.part_id): lot for lot in found.scalars()}

    async def add(self, lot: StockLot) -> None:
        self._session.add(lot)

    async def locations_of(self, lot_ids: Collection[StockLotId]) -> dict[StockLotId, Location]:
        """Each lot's location, `stock_lots` joined to `locations` in one statement.

        `= ANY(:ids)` binds one array, so the statement is the same for one lot or two hundred;
        both tables are filtered on the workspace, and a lot it doesn't hold is absent.
        """
        if not lot_ids:
            return {}
        found = await self._session.execute(
            select(stock_lots.c.id, Location)
            .select_from(stock_lots.join(locations, locations.c.id == stock_lots.c.location_id))
            .where(
                stock_lots.c.workspace_id == self._workspace_id,
                locations.c.workspace_id == self._workspace_id,
                stock_lots.c.id == any_(literal(list(lot_ids), ARRAY(Uuid))),
            )
        )
        return {StockLotId(lot_id): location for lot_id, location in found.tuples()}

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

    async def sums_of_revision(self, revision_id: RevisionId) -> list[MovementSum]:
        """A revision's changes grouped by lot, part, location and kind, in one query (8.5).

        Over the partial index `(workspace_id, revision_id) WHERE revision_id IS NOT NULL`, so
        a revision's rows are found without scanning the ledger (design's decision 1). The lot,
        its part and its location code come from the join to `stock_lots` and `locations`;
        `HeldStock.of` does the fold, this only sums.
        """
        rows = await self._session.execute(
            self._grouped_sums().where(stock_movements.c.revision_id == revision_id)
        )
        return [_sum_of(row) for row in rows]

    async def sums_of_part(self, part_id: PartId) -> dict[RevisionId, list[MovementSum]]:
        """One part's rows grouped by revision, lot, location and kind, in one query (10.4).

        Only the rows naming a revision touch a part's holdings, so the query keeps
        `revision_id IS NOT NULL`, using the same partial index; the caller folds each
        revision's sums with `HeldStock.of` (requirement 10.6).
        """
        rows = await self._session.execute(
            self._grouped_sums(with_revision=True).where(
                stock_lots.c.part_id == part_id,
                stock_movements.c.revision_id.isnot(None),
            )
        )
        return _sums_by_revision(rows)

    async def sums_of_holdings(self) -> dict[RevisionId, list[MovementSum]]:
        """Every revision's rows grouped by revision, lot, location and kind, in one query
        (18-dashboard, decision 1).

        `sums_of_part` without its part filter, over the same partial index: only rows naming
        a revision touch a holding. The caller folds each revision's sums with `HeldStock.of`
        and regroups them per part.
        """
        rows = await self._session.execute(
            self._grouped_sums(with_revision=True).where(stock_movements.c.revision_id.isnot(None))
        )
        return _sums_by_revision(rows)

    def _grouped_sums(self, *, with_revision: bool = False) -> Select[Any]:
        """The grouped-sum query shared by `sums_of_revision`, `sums_of_part` and
        `sums_of_holdings`.

        Sums `change` by (lot, part, location, kind), joining the lot for its part and location
        and the location for its code. `with_revision` also selects and groups by the revision,
        for the two reads that fold their rows per revision.
        """
        columns = [
            stock_movements.c.lot_id,
            stock_lots.c.part_id,
            stock_lots.c.location_id,
            locations.c.code,
            stock_movements.c.kind,
            func.sum(stock_movements.c.change).label("change"),
        ]
        group_by = [
            stock_movements.c.lot_id,
            stock_lots.c.part_id,
            stock_lots.c.location_id,
            locations.c.code,
            stock_movements.c.kind,
        ]
        if with_revision:
            columns.insert(0, stock_movements.c.revision_id)
            group_by.append(stock_movements.c.revision_id)
        return (
            select(*columns)
            .select_from(
                stock_movements.join(stock_lots, stock_lots.c.id == stock_movements.c.lot_id).join(
                    locations, locations.c.id == stock_lots.c.location_id
                )
            )
            .where(stock_movements.c.workspace_id == self._workspace_id)
            .group_by(*group_by)
        )

    def _mine(self) -> Select[tuple[StockMovement]]:
        return select(StockMovement).where(stock_movements.c.workspace_id == self._workspace_id)


_CHANGED_MEANWHILE = "the stock changed while this was being saved; try again"


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
            )
            .where(
                stock_balances.c.workspace_id == self._workspace_id,
                stock_balances.c.lot_id == lot_id,
            )
            # Locked until commit: a concurrent movement on this lot waits here and then reads
            # the balance this one wrote, so no movement's effect is lost (5.5).
            .with_for_update()
        )
        row = found.one_or_none()
        return None if row is None else _balance_of(row)

    async def put(self, balance: StockBalance) -> None:
        """Write a balance whose `version` follows the stored one, or raise (5.5, 14.3).

        The version says which write this is, so no SELECT runs first: a transition's reads
        stay fixed however many lots it touches (design decision 17). Version 1 is a lot's
        first balance and inserts; a later version updates the row whose stored version is one
        behind and bumps it. A first write that finds the row already there — two transactions
        both creating the lot's first balance — and an update matching nothing — a stale write,
        or something that wrote the balance outside a movement — are both the
        `ConcurrentStockError` it is today, and the transaction, the movement included, rolls
        back; a silent miss would leave the ledger and the balance disagreeing. `available` is
        derived on the entity and written from its property, which keeps the CHECK
        `available = on_hand - reserved` satisfied.
        """
        await self._session.flush()
        values = {
            "on_hand": balance.on_hand,
            "reserved": balance.reserved,
            "available": int(balance.available),
            "version": balance.version,
        }
        if balance.version == 1:
            try:
                async with self._session.begin_nested():
                    await self._session.execute(
                        stock_balances.insert().values(
                            lot_id=balance.lot_id, workspace_id=self._workspace_id, **values
                        )
                    )
            except IntegrityError as error:
                raise ConcurrentStockError(_CHANGED_MEANWHILE) from error
            return
        updated = await self._session.execute(
            stock_balances.update()
            .where(
                stock_balances.c.lot_id == balance.lot_id,
                stock_balances.c.workspace_id == self._workspace_id,
                stock_balances.c.version == balance.version - 1,
            )
            .values(**values)
        )
        if cast("CursorResult[Any]", updated).rowcount != 1:
            raise ConcurrentStockError(_CHANGED_MEANWHILE)

    async def totals_by_part(self, part_ids: Sequence[PartId]) -> dict[PartId, int]:
        """The total on_hand per part across its lots, one grouped query (7.1, 7.2).

        `stock_balances` joined to `stock_lots` on `lot_id`, summed by `part_id`, so the parts
        list never loads a balance per row. A part with no stock isn't in the result; the
        caller reads a missing part as zero.
        """
        return await self._sum_by_part(stock_balances.c.on_hand, part_ids)

    async def available_by_part(self, part_ids: Sequence[PartId]) -> dict[PartId, int]:
        """The total available per part, the same grouped query over `available`.

        `available` is stored and CHECKed per balance (ADR 0002), so the sum needs no unit
        logic: a unit-tracked part's lots hold its in-stock units (06), and what a BOM's
        shortage report reads is one statement whatever its size (09's requirement 12.3).
        """
        return await self._sum_by_part(stock_balances.c.available, part_ids)

    async def stocked_parts(self) -> set[PartId]:
        """Every part whose lots hold some stock, one grouped query over the same join the
        totals sum: a part counts as stocked exactly when its stock column reads above zero."""
        rows = await self._session.execute(
            select(stock_lots.c.part_id)
            .select_from(
                stock_lots.join(stock_balances, stock_balances.c.lot_id == stock_lots.c.id)
            )
            .where(stock_lots.c.workspace_id == self._workspace_id)
            .group_by(stock_lots.c.part_id)
            .having(func.sum(stock_balances.c.on_hand) > 0)
        )
        return {PartId(part_id) for part_id in rows.scalars()}

    async def _sum_by_part(
        self, column: ColumnElement[int], part_ids: Sequence[PartId]
    ) -> dict[PartId, int]:
        if not part_ids:
            return {}
        rows = await self._session.execute(
            select(stock_lots.c.part_id, func.coalesce(func.sum(column), 0))
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
        """A part's on_hand and reserved broken down by location (requirements 7.3, 10.3).

        `stock_balances` joined through `stock_lots` to `locations`, so one query carries the
        on_hand, the reserved and the location they sit in; available is on_hand less reserved,
        computed by `LotBalance`. Ordered by the location code, a stable order the breakdown
        reads well in.
        """
        found = await self._session.execute(
            select(Location, stock_balances.c.on_hand, stock_balances.c.reserved)
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
            LotBalance(
                location=location,
                on_hand=Quantity(int(on_hand)),
                reserved=Quantity(int(reserved)),
            )
            for location, on_hand, reserved in found.tuples()
        ]

    async def at_location(self, location_id: LocationId) -> list[LotHolding]:
        """The lots in the location with their balances, `stock_lots` outer-joined to
        `stock_balances` in one statement: a lot with no balance row yet holds nothing. Both
        tables are filtered on the workspace; the caller orders the lots by part name."""
        found = await self._session.execute(
            select(
                stock_lots.c.id,
                stock_lots.c.part_id,
                func.coalesce(stock_balances.c.on_hand, 0),
                func.coalesce(stock_balances.c.reserved, 0),
            )
            .select_from(
                stock_lots.outerjoin(
                    stock_balances,
                    (stock_balances.c.lot_id == stock_lots.c.id)
                    & (stock_balances.c.workspace_id == self._workspace_id),
                )
            )
            .where(
                stock_lots.c.workspace_id == self._workspace_id,
                stock_lots.c.location_id == location_id,
            )
            .order_by(stock_lots.c.id)
        )
        return [
            LotHolding(
                lot_id=StockLotId(lot_id),
                part_id=PartId(part_id),
                on_hand=Quantity(int(on_hand)),
                reserved=Quantity(int(reserved)),
            )
            for lot_id, part_id, on_hand, reserved in found.tuples()
        ]

    async def lock(self, lot_ids: Sequence[StockLotId]) -> list[LockedLot]:
        """Lock these lots' balances FOR UPDATE, in lot-id order, with part and code (10).

        The caller has sorted the ids. Each lot's row and its balance row are locked; a lot
        with no balance yet — a fresh return lot — comes back with its opening balance, so the
        caller writes the first `put`. The `StockLot` is read with `populate_existing`, so a
        lot already in the session is refreshed with what the lock saw (decision 10).
        """
        if not lot_ids:
            return []
        return await self._locked(stock_lots.c.id.in_(lot_ids))

    async def lock_by_part(self, part_ids: Sequence[PartId]) -> list[LockedLot]:
        """Lock every lot of these parts FOR UPDATE, in lot-id order, with part and code (2.8).

        What a reserve locks, so the second of two reserves on one part sees what the first
        left. Same lot-id order and `populate_existing` as `lock`.
        """
        if not part_ids:
            return []
        return await self._locked(stock_lots.c.part_id.in_(part_ids))

    async def _locked(self, predicate: ColumnElement[bool]) -> list[LockedLot]:
        """Lots matching the predicate with their balances and location codes, FOR UPDATE in
        lot-id order (decision 10). The lot is read as an ORM entity with `populate_existing`;
        the balance is a raw row, locked by the same statement, opening when absent."""
        found = await self._session.execute(
            select(
                StockLot,
                locations.c.code,
                stock_balances.c.on_hand,
                stock_balances.c.reserved,
                stock_balances.c.version,
            )
            .select_from(
                stock_lots.join(locations, locations.c.id == stock_lots.c.location_id).outerjoin(
                    stock_balances, stock_balances.c.lot_id == stock_lots.c.id
                )
            )
            .where(stock_lots.c.workspace_id == self._workspace_id, predicate)
            .order_by(stock_lots.c.id)
            # `FOR UPDATE OF stock_lots` only: Postgres won't lock the nullable side of an
            # outer join, and a fresh return lot has no balance row yet. The balance itself is
            # locked when `RevisionStock` reads it through `BalanceSheet.get` before its write;
            # task 7 pins the exact lock statement and its count.
            .with_for_update(of=stock_lots)
            .execution_options(populate_existing=True)
        )
        locked: list[LockedLot] = []
        for lot, code, on_hand, reserved, version in found:
            balance = (
                StockBalance.opening(lot.id)
                if version is None
                else StockBalance(
                    lot_id=lot.id, on_hand=on_hand, reserved=reserved, version=version
                )
            )
            locked.append(LockedLot(lot=lot, balance=balance, location_code=str(code)))
        return locked

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


class SqlUnits:
    """A workspace's units, each an identity row pointing at a lot (design's decision 1).

    Every query filters `workspace_id` itself, ADR 0007's first gate, on top of the policies.
    The two uniqueness checks mirror the partial indexes the table carries: `serial_taken`
    folds case with `lower(serial)`, the per-part index's expression, so it uses that index;
    `mac_taken` compares the already-canonical stored MAC, the per-workspace index. `search`
    matches a case-insensitive substring over the code, serial and MAC trigram indexes.
    """

    def __init__(self, session: AsyncSession, workspace_id: WorkspaceId) -> None:
        self._session = session
        self._workspace_id = workspace_id

    async def get(self, unit_id: UnitId) -> Unit | None:
        # Not session.get(): another workspace's id has to come back as nothing found, never
        # as a row the policy would then hide only on read. Locked for the transaction, like a
        # balance: two retires or moves of one unit at once would each see it in stock and
        # each write their movement.
        found = await self._session.execute(
            self._mine().where(units.c.id == unit_id).with_for_update()
        )
        return found.scalar_one_or_none()

    async def of_ids(self, unit_ids: Collection[UnitId]) -> list[Unit]:
        """The listed units the workspace holds, by code, in one statement (15-flash-log
        decision 8).

        `= ANY(:ids)` binds one array, so the statement is the same for one id or forty. No
        row lock, unlike `get`: firmware's unit directory reads these to show them, and the
        one write that must take turns with a retire, a flash, locks its unit through `get`.
        An id the workspace doesn't hold, another workspace's included, is simply absent.
        """
        if not unit_ids:
            return []
        found = await self._session.execute(
            self._mine()
            .where(units.c.id == any_(literal(list(unit_ids), ARRAY(Uuid))))
            .order_by(units.c.code)
        )
        return list(found.scalars())

    async def add(self, unit: Unit) -> None:
        self._session.add(unit)

    async def of_part(self, part_id: PartId) -> list[Unit]:
        """The part's units, over the (workspace, part) index, code order (requirement 6.1)."""
        found = await self._session.execute(
            self._mine().where(units.c.part_id == part_id).order_by(units.c.code)
        )
        return list(found.scalars())

    async def of_lot(self, lot_id: StockLotId) -> list[Unit]:
        """The units sitting in a lot, over the (workspace, lot) index (requirement 6.2)."""
        found = await self._session.execute(
            self._mine().where(units.c.lot_id == lot_id).order_by(units.c.code)
        )
        return list(found.scalars())

    async def of_location(self, location_id: LocationId) -> list[Unit]:
        """The units at a location, across every lot there, in one join (requirement 6.2).

        A unit's location is its lot's location, so `units` joins `stock_lots` on `lot_id` and
        the lots at the location are kept — never another location's, never another workspace's
        (both tables are filtered on `workspace_id`).
        """
        found = await self._session.execute(
            select(Unit)
            .select_from(units.join(stock_lots, stock_lots.c.id == units.c.lot_id))
            .where(
                units.c.workspace_id == self._workspace_id,
                live(units),
                stock_lots.c.workspace_id == self._workspace_id,
                stock_lots.c.location_id == location_id,
            )
            .order_by(units.c.code)
        )
        return list(found.scalars())

    async def in_stock_at(self, lot_id: StockLotId) -> int:
        """How many `in_stock` units point at the lot, the count the invariant checks (9.1)."""
        found = await self._session.scalar(
            select(func.count())
            .select_from(units)
            .where(
                units.c.workspace_id == self._workspace_id,
                units.c.lot_id == lot_id,
                units.c.status == UnitStatus.IN_STOCK,
            )
        )
        return int(found or 0)

    async def of_revision(self, revision_id: RevisionId) -> list[RevisionUnitRow]:
        """The units a revision holds, joined to their lots and locations, in one query (3.11).

        Over the partial index `(workspace_id, revision_id) WHERE revision_id IS NOT NULL`. A
        unit in use answers no location — it sits on a board, not in the drawer — so the
        location code is left `None` for it (design's decision 5); a reserved unit answers its
        lot's location code. Ordered by code, the order the holdings read in.
        """
        found = await self._session.execute(
            select(Unit, locations.c.code)
            .select_from(
                units.join(stock_lots, stock_lots.c.id == units.c.lot_id).join(
                    locations, locations.c.id == stock_lots.c.location_id
                )
            )
            .where(
                units.c.workspace_id == self._workspace_id,
                units.c.revision_id == revision_id,
            )
            .order_by(units.c.code)
        )
        return [
            RevisionUnitRow(
                unit=unit,
                location_code=None if unit.status is UnitStatus.IN_USE else str(code),
            )
            for unit, code in found.tuples()
        ]

    async def lock(self, unit_ids: Sequence[UnitId]) -> list[Unit]:
        """Lock these units FOR UPDATE, in id order, with `populate_existing` (decision 10).

        The caller has sorted the ids. A unit already in the session is refreshed with what
        the lock saw; an id the workspace doesn't hold is simply absent from the result.
        """
        if not unit_ids:
            return []
        found = await self._session.execute(
            self._mine()
            .where(units.c.id.in_(unit_ids))
            .order_by(units.c.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return list(found.scalars())

    async def in_stock_of_parts(self, part_ids: Sequence[PartId]) -> list[Unit]:
        """The in-stock units of these parts, locked FOR UPDATE in id order (decision 10)."""
        if not part_ids:
            return []
        found = await self._session.execute(
            self._mine()
            .where(
                units.c.part_id.in_(part_ids),
                units.c.status == UnitStatus.IN_STOCK,
            )
            .order_by(units.c.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return list(found.scalars())

    async def of_lot_reserved(self, lot_id: StockLotId) -> int:
        """How many `reserved` units point at the lot, the other half of the invariant (3.9)."""
        found = await self._session.scalar(
            select(func.count())
            .select_from(units)
            .where(
                units.c.workspace_id == self._workspace_id,
                units.c.lot_id == lot_id,
                units.c.status == UnitStatus.RESERVED,
            )
        )
        return int(found or 0)

    async def search(self, query: UnitQuery, limit: int) -> list[Unit]:
        """The units the query keeps, newest first, at most `limit`, in one statement (6.3).

        A term is three `ILIKE '%term%'` the code, serial and MAC trigram GIN indexes answer,
        OR-ed so one term finds a board by any of its three identities; the caller has trimmed
        it, a blank one narrows nothing, and its wildcards are escaped to characters. The
        status and the part are plain equalities, the part's over the (workspace, part) index.
        Newest first is by when a unit was received, its id breaking ties, as UUIDv7 ids sort.
        """
        statement = self._mine()
        if query.term:
            statement = statement.where(_identified_by(_containing(query.term)))
        if query.status is not None:
            statement = statement.where(units.c.status == query.status)
        if query.part_id is not None:
            statement = statement.where(units.c.part_id == query.part_id)
        found = await self._session.execute(
            statement.order_by(units.c.created_at.desc(), units.c.id.desc()).limit(limit)
        )
        return list(found.scalars())

    async def find(self, text: str, limit: int) -> list[Unit]:
        found = await self._session.execute(
            self._mine()
            .where(_identified_by(_containing(text)))
            .order_by(*_starting_first(units.c.code, text), units.c.id)
            .limit(limit)
        )
        return list(found.scalars())

    async def serial_taken(self, part_id: PartId, serial: Serial) -> bool:
        """Whether another unit of the part already holds the serial, folding case (5.1).

        Compares on `lower(serial)`, the expression the per-part partial index is built on, so
        the check uses that index and agrees with what the index enforces on write.
        """
        found = await self._session.scalar(
            select(literal(True))
            .select_from(units)
            .where(
                units.c.workspace_id == self._workspace_id,
                units.c.part_id == part_id,
                units.c.serial.isnot(None),
                func.lower(units.c.serial) == serial.fold(),
            )
            .limit(1)
        )
        return found is not None

    async def mac_taken(self, mac: Mac) -> bool:
        """Whether another unit in the workspace already holds the MAC (requirement 5.2).

        The stored MAC is already canonical (the `Mac` value lower-cased it), so this compares
        the canonical string against the per-workspace partial index directly, no `lower()`.
        """
        found = await self._session.scalar(
            select(literal(True))
            .select_from(units)
            .where(
                units.c.workspace_id == self._workspace_id,
                units.c.mac == str(mac),
            )
            .limit(1)
        )
        return found is not None

    async def remove(self, unit: Unit) -> None:
        await self._session.delete(unit)

    async def trashed(
        self, count: int, text: str | None, part_ids: frozenset[PartId]
    ) -> TrashedSlice[Unit]:
        """The newest of the trash and their total in one statement, over `ix_units_trashed`
        (16's decision 9)."""
        statement = self._any()
        if text is not None:
            statement = statement.where(
                units.c.code.ilike(_containing(text), escape=_LIKE_ESCAPE)
                | (units.c.part_id == any_(literal(list(part_ids), ARRAY(Uuid))))
            )
        found = await self._session.execute(trash_newest(statement, units, count))
        return sliced(found.tuples())

    async def in_trash(self, unit_id: UnitId) -> Unit | None:
        """Locked and fresh, so a restore and a delete for good of one unit take turns, and the
        second finds nothing (16's decision 10)."""
        found = await self._session.execute(
            self._any()
            .where(units.c.id == unit_id, in_the_trash(units))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return found.scalar_one_or_none()

    async def empty_trash(self) -> int:
        """One `DELETE`; each row it takes is locked and checked again, so a restore racing it
        either wins or finds nothing. Nothing keys into a unit, and its movements stay."""
        result = await self._session.execute(
            delete(units).where(units.c.workspace_id == self._workspace_id, in_the_trash(units))
        )
        return cast("CursorResult[Any]", result).rowcount

    def _mine(self) -> Select[tuple[Unit]]:
        """The workspace's live units: every read but the trash's own and the two uniqueness
        checks goes through here, so a unit in the trash is absent everywhere (16's decision
        2). `get`, `lock` and `in_stock_of_parts` lock through it, so a lock taken after a move
        to the trash finds nothing (decision 3)."""
        return self._any().where(live(units))

    def _any(self) -> Select[tuple[Unit]]:
        """The workspace's units, in the trash or not."""
        return select(Unit).where(units.c.workspace_id == self._workspace_id)


def _balance_of(row: Row[tuple[StockLotId, Quantity, Quantity, int]]) -> StockBalance:
    """One row as a balance. `on_hand` and `reserved` come back as `Quantity` already, through
    the column's `QuantityType`. `available` is derived, so it isn't read: the entity
    recomputes it, and the CHECK guaranteed the stored row agreed."""
    lot_id, on_hand, reserved, version = row
    return StockBalance(lot_id=lot_id, on_hand=on_hand, reserved=reserved, version=version)


def _sum_of(row: Row[Any]) -> MovementSum:
    """One grouped row as a `MovementSum`. `code` comes back through `ShortCodeType` as a
    `ShortCode`, so it is stringified for the plain-str `location_code` field."""
    return MovementSum(
        lot_id=StockLotId(row.lot_id),
        part_id=PartId(row.part_id),
        location_id=LocationId(row.location_id),
        location_code=str(row.code),
        kind=MovementKind(row.kind),
        change=int(row.change),
    )


def _sums_by_revision(rows: Iterable[Row[Any]]) -> dict[RevisionId, list[MovementSum]]:
    """Grouped rows that carry their revision, as each revision's `MovementSum`s."""
    by_revision: dict[RevisionId, list[MovementSum]] = {}
    for row in rows:
        by_revision.setdefault(RevisionId(row.revision_id), []).append(_sum_of(row))
    return by_revision


def _containing(text_value: str) -> str:
    return f"%{text_value.translate(_LIKE_WILDCARDS)}%"


def _identified_by(pattern: str) -> ColumnElement[bool]:
    """A unit whose code, serial or MAC matches the pattern: three `ILIKE`s the code, serial and
    MAC trigram GIN indexes answer, OR-ed so one term finds a board by any of its identities."""
    return (
        units.c.code.ilike(pattern, escape=_LIKE_ESCAPE)
        | units.c.serial.ilike(pattern, escape=_LIKE_ESCAPE)
        | units.c.mac.ilike(pattern, escape=_LIKE_ESCAPE)
    )


def _starting_first(title: ColumnElement[Any], text_value: str) -> tuple[ColumnElement[Any], ...]:
    """A find's order (19-command-palette, decision 2): the titles starting with the text
    first, then the rest, each by the title folded. `COLLATE "C"` orders by code point, as
    Python's sort does, whatever collation the database was created with."""
    starting = f"{text_value.translate(_LIKE_WILDCARDS)}%"
    return (
        title.ilike(starting, escape=_LIKE_ESCAPE).desc(),
        func.lower(title).collate("C"),
    )
