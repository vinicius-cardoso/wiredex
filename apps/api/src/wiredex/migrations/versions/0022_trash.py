"""trash

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-01 18:46:18.480322

The trash's schema (16-soft-delete-and-trash, Data Models): the four records with a page of their
own, `part_definitions`, `units`, `projects` and `firmware`, each learn when they moved to the
trash. A record is in the trash while `trashed_at` is set; what it holds (a part's pins, a
project's revisions, a firmware's versions) carries no column and is in the trash with its root
(decision 1).

Details worth knowing when reading the DDL:

- `ix_<table>_trashed` leads with the workspace, then the trash's own order, newest first, the
  id breaking ties (decision 9): a page of the trash before a cursor reads in index order. It is
  partial, so the live rows, nearly all of them, cost it nothing.
- No unique index changes: a record in the trash keeps its name, MPN, serial and MAC (decision 5).

Purely additive: four nullable columns with no default rewrite nothing, and four indexes over no
rows yet, so the release before this one keeps working against the schema. That release ignores
the column, so after a rollback of the API what is in the trash shows as live again, and loses
nothing; since no unique index changed, no two rows clash when it does. `downgrade` drops the
indexes and the columns, which is the same: what was in the trash comes back. The tables are
already isolated by workspace, so ADR 0007's list is unchanged.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | None = None
depends_on: str | None = None

_ROOTS = ("part_definitions", "units", "projects", "firmware")
_TRASHED = sa.text("trashed_at IS NOT NULL")


def upgrade() -> None:
    for table in _ROOTS:
        op.add_column(table, sa.Column("trashed_at", sa.DateTime(timezone=True), nullable=True))
        op.create_index(
            f"ix_{table}_trashed",
            table,
            ["workspace_id", sa.literal_column("trashed_at DESC"), sa.literal_column("id DESC")],
            unique=False,
            postgresql_where=_TRASHED,
        )


def downgrade() -> None:
    for table in reversed(_ROOTS):
        op.drop_index(f"ix_{table}_trashed", table_name=table, postgresql_where=_TRASHED)
        op.drop_column(table, "trashed_at")
