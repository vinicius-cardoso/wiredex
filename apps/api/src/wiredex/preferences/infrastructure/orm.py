"""The `workspace_preferences` table: one row per workspace that saved a choice.

Workspace-scoped, so migration `0028` ends with `isolate_by_workspace` and the API, connecting
as `wiredex_app`, sees only its own row (ADR 0007).
"""

from sqlalchemy import Column, Enum, Table, Uuid

from wiredex.preferences.domain.preferences import StockBasis, WorkspacePreferences
from wiredex.shared_kernel.infrastructure.orm import mapper_registry, metadata

workspace_preferences = Table(
    "workspace_preferences",
    metadata,
    # The workspace is the key: there is one row of choices for each, or none yet.
    Column("workspace_id", Uuid, primary_key=True),
    Column(
        "stock_basis",
        # Text with a CHECK, never a Postgres enum type: a third basis is then a CHECK and a
        # union, not an ALTER TYPE.
        Enum(
            StockBasis,
            name="stock_basis",
            native_enum=False,
            create_constraint=True,
            values_callable=lambda members: [member.value for member in members],
            length=16,
        ),
        nullable=False,
    ),
)

mapper_registry.map_imperatively(WorkspacePreferences, workspace_preferences)
