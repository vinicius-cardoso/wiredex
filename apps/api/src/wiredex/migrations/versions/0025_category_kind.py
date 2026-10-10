"""category kind

Revision ID: 0025
Revises: 0024
Create Date: 2026-10-10 21:30:00.000000

The `mechanical` flag on categories, which says their parts are bolts and inserts rather than
electronic components: no pinout and never wired (21-part-kinds). NULL means "inherit from the
parent"; a set value overrides, as `tracked_individually` and `not_stocked` do, and the three
resolve independently in the application. Nothing set anywhere is electronic, which is what
every part was before, so no row needs a value.

Additive and nullable, over the existing `categories` table: there is no new table, so no
`isolate_by_workspace`. The release before this one never selects the column and its inserts
leave it null, so it keeps working against the schema.

`downgrade` drops the column, and the kind with it: every part reads as electronic again.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("categories", sa.Column("mechanical", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("categories", "mechanical")
