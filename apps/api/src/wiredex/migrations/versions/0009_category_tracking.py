"""category tracking

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-26 19:18:19.154100

The `tracked_individually` flag on categories, which inventory reads to refuse a lot
receive into a unit-tracked part (design's catalog change, requirements 6.1, 6.2). NULL
means "inherit from the parent"; a set value overrides. Resolution along the ancestor
chain is the application's, so the column just stores the three states.

Additive and nullable, over the existing `categories` table: nothing here is a new table,
so there is no `isolate_by_workspace` — the row-level security 0005 turned on for
`categories` already covers every column of the row. The release before this one keeps
working against the schema, since the column is optional (expand now, contract later).

`downgrade` drops the column, which drops the flag with it; no data outside this column
depends on it.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("categories", sa.Column("tracked_individually", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("categories", "tracked_individually")
