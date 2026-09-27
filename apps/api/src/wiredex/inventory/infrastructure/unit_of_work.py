from typing import Self

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from wiredex.inventory.domain.values import WorkspaceId
from wiredex.inventory.infrastructure.orm import (
    locations,
    short_code_counters,
    stock_balances,
    stock_lots,
    stock_movements,
)
from wiredex.inventory.infrastructure.repositories import (
    SqlBalanceSheet,
    SqlLedger,
    SqlLocations,
    SqlLots,
    SqlShortCodes,
)
from wiredex.shared_kernel.infrastructure.unit_of_work import SqlUnitOfWork

# Deleted in foreign-key order for a demo reset: movements and balances point at lots, lots at
# locations (RESTRICT), so the leaves go before the tables they reference. The counter is
# cleared too, so a restored bench numbers its locations from WX-L-0001 again.
_CLEAR_ORDER = (stock_movements, stock_balances, stock_lots, locations, short_code_counters)


class SqlInventoryUnitOfWork(SqlUnitOfWork):
    """One transaction with the inventory repositories bound to its session and workspace.

    The workspace is required here, unlike in the base: every inventory row belongs to one,
    and both of ADR 0007's gates need it — the repositories filter on it, and the base names
    it to Postgres so the policies on these tables apply. The repositories are exposed as
    plain attributes, which the read-only properties of the `InventoryUnitOfWork` port accept.
    """

    locations: SqlLocations
    lots: SqlLots
    ledger: SqlLedger
    balances: SqlBalanceSheet
    short_codes: SqlShortCodes

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        workspace_id: WorkspaceId,
    ) -> None:
        super().__init__(session_factory, workspace_id)
        # Kept under its own name: the base holds a plain UUID, and the repositories speak the
        # inventory's WorkspaceId.
        self._workspace = workspace_id

    async def __aenter__(self) -> Self:
        await super().__aenter__()
        self.locations = SqlLocations(self.session, self._workspace)
        self.lots = SqlLots(self.session, self._workspace)
        self.ledger = SqlLedger(self.session, self._workspace)
        self.balances = SqlBalanceSheet(self.session, self._workspace)
        self.short_codes = SqlShortCodes(self.session, self._workspace)
        return self

    async def clear(self) -> None:
        """Empty this workspace's inventory, for a demo bench being restored (ADR 0007, 8.6).

        Every table is deleted in foreign-key order and filtered on `workspace_id` itself, so
        it clears only this bench's rows even before the policies narrow it — the same
        defence-in-depth the repositories keep. The caller commits.
        """
        for table in _CLEAR_ORDER:
            await self.session.execute(delete(table).where(table.c.workspace_id == self._workspace))
