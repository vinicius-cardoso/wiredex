"""minimum stock

Revision ID: 0028
Revises: 0027
Create Date: 2026-10-11 12:00:00.000000

A part can say the least to keep on hand, a category the default for its parts, and a
workspace what that minimum is compared against (24-minimum-stock):

- `part_definitions.minimum_stock` and `categories.minimum_stock`, nullable integers with a
  CHECK for 0 to 1,000,000. NULL on a part takes its category's default; NULL on a category
  inherits its parent's.
- `workspace_preferences`, one row per workspace that saved a choice, holding `stock_basis`:
  `free` or `total`. Workspace-scoped, so it ends with `isolate_by_workspace`; `0004`'s
  default privileges already let the app role read and write it.

Only additions, so the release before this one keeps working against the schema: it neither
reads nor writes the columns, and never touches the table.

`downgrade` drops the table and both columns, and with them the minimums and choices saved
since.
"""

import sqlalchemy as sa
from alembic import op

from wiredex.shared_kernel.infrastructure.row_security import isolate_by_workspace

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | None = None
depends_on: str | None = None

_IN_RANGE = "minimum_stock >= 0 AND minimum_stock <= 1000000"


def upgrade() -> None:
    for table in ("part_definitions", "categories"):
        op.add_column(table, sa.Column("minimum_stock", sa.Integer(), nullable=True))
        op.create_check_constraint(op.f(f"ck_{table}_minimum_stock_range"), table, _IN_RANGE)
    op.create_table(
        "workspace_preferences",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("stock_basis", sa.String(length=16), nullable=False),
        sa.CheckConstraint(
            "stock_basis IN ('free', 'total')", name=op.f("ck_workspace_preferences_stock_basis")
        ),
        sa.PrimaryKeyConstraint("workspace_id", name=op.f("pk_workspace_preferences")),
    )
    isolate_by_workspace(op.execute, "workspace_preferences")


def downgrade() -> None:
    op.drop_table("workspace_preferences")
    for table in ("categories", "part_definitions"):
        op.drop_constraint(op.f(f"ck_{table}_minimum_stock_range"), table, type_="check")
        op.drop_column(table, "minimum_stock")
