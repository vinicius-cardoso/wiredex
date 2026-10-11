"""The `workspace_preferences` table: one row per workspace that saved a choice.

Workspace-scoped, so migration `0028` ends with `isolate_by_workspace` and the API, connecting
as `wiredex_app`, sees only its own row (ADR 0007). Each column added since has a server
default or is nullable, so a release that doesn't know it can still insert a row.
"""

from enum import StrEnum

from sqlalchemy import CheckConstraint, Column, Enum, Integer, String, Table, Uuid, text

from wiredex.preferences.domain.preferences import (
    DateFormat,
    NumberFormat,
    StockBasis,
    WorkspacePreferences,
)
from wiredex.shared_kernel.infrastructure.orm import mapper_registry, metadata


def _choice(enum: type[StrEnum], name: str) -> Enum:
    # Text with a CHECK, never a Postgres enum type: one more option is then a CHECK and a
    # union, not an ALTER TYPE.
    return Enum(
        enum,
        name=name,
        native_enum=False,
        create_constraint=True,
        values_callable=lambda members: [member.value for member in members],
        length=16,
    )


workspace_preferences = Table(
    "workspace_preferences",
    metadata,
    # The workspace is the key: there is one row of choices for each, or none yet.
    Column("workspace_id", Uuid, primary_key=True),
    Column("stock_basis", _choice(StockBasis, "stock_basis"), nullable=False),
    Column("default_minimum_stock", Integer, nullable=True),
    Column("code_prefix", String(6), nullable=False, server_default=text("'WX'")),
    Column(
        "date_format",
        _choice(DateFormat, "date_format"),
        nullable=False,
        server_default=text("'language'"),
    ),
    Column(
        "number_format",
        _choice(NumberFormat, "number_format"),
        nullable=False,
        server_default=text("'language'"),
    ),
    Column("trash_retention_days", Integer, nullable=True),
    CheckConstraint(
        "default_minimum_stock >= 0 AND default_minimum_stock <= 1000000",
        name="default_minimum_stock_range",
    ),
    CheckConstraint("code_prefix ~ '^[A-Z][A-Z0-9]{0,5}$'", name="code_prefix_shape"),
    CheckConstraint(
        "trash_retention_days >= 1 AND trash_retention_days <= 3650",
        name="trash_retention_days_range",
    ),
)

mapper_registry.map_imperatively(WorkspacePreferences, workspace_preferences)
