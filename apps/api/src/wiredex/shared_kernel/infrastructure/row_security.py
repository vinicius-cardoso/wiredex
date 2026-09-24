"""Workspace isolation in Postgres, the second gate of ADR 0007.

Tables holding a workspace's data turn on row-level security in their migration, with
`isolate_by_workspace`. Every transaction then names its workspace with
`scope_to_workspace`, and Postgres shows and accepts only that workspace's rows, even
if a query forgets its filter. The API's role, wiredex_app, is subject to this; the
schema owner, a superuser, isn't: that is the admin path.

Migrations that already ran depend on these statements: don't change what they do.
"""

from collections.abc import Callable
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

WORKSPACE_SETTING = "app.workspace_id"
POLICY = "workspace_isolation"
# After a transaction that set it ends, the setting reads as '' rather than NULL. Both
# mean "no workspace", which matches no rows.
_CURRENT_WORKSPACE = f"NULLIF(current_setting('{WORKSPACE_SETTING}', true), '')::uuid"

type Execute = Callable[[str], object]


def isolate_by_workspace(execute: Execute, table: str) -> None:
    """Limit TABLE to the current workspace's rows, for reads and writes alike.

    In a migration: `isolate_by_workspace(op.execute, "parts")`. The table needs a
    `workspace_id uuid` column.
    """
    execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    execute(
        f"CREATE POLICY {POLICY} ON {table}"
        f" USING (workspace_id = {_CURRENT_WORKSPACE})"
        f" WITH CHECK (workspace_id = {_CURRENT_WORKSPACE})"
    )


async def scope_to_workspace(session: AsyncSession, workspace_id: UUID) -> None:
    """Name the workspace for the rest of the session's current transaction only."""
    await session.execute(select(func.set_config(WORKSPACE_SETTING, str(workspace_id), True)))
