"""category stocking

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-28 16:28:41.824802

The `not_stocked` flag on categories, which marks their parts as consumables: inventory
refuses to receive them and a bill of materials never counts them short (09's decisions 2
to 4). NULL means "inherit from the parent"; a set value overrides, as `0009`'s
`tracked_individually` does, and the two resolve independently in the application. The column
just stores the three states.

Additive and nullable, over the existing `categories` table: nothing here is a new table,
so there is no `isolate_by_workspace` — the row-level security 0005 turned on for
`categories` already covers every column of the row. The release before this one never
selects the column and its inserts leave it null, so it keeps working against the schema.

`downgrade` drops the column, which drops the flag with it; no data outside this column
depends on it.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("categories", sa.Column("not_stocked", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("categories", "not_stocked")
