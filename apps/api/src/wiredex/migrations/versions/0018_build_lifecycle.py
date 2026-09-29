"""build lifecycle

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-28 23:39:27.985072

The build lifecycle's schema (v0.5.0, spec 10, design's decision 6). Two tables grow so a
build can hold stock: `units` learns the two held statuses and the revision a held unit
belongs to, and `stock_movements` gets the CHECKs that keep the four new ledger kinds
(RESERVE, RELEASE, CONSUME, RETURN) honest. What a revision holds is folded from the ledger,
so no table is new and there is no reservations table.

Purely additive (requirement 14.2): it widens a CHECK, adds a nullable column with no default,
adds CHECKs and partial indexes, and every row the previous release wrote satisfies them, so
that release keeps working against this schema and a failed deploy that rolls the API back but
not the schema still runs.

- The previous release's movements are RECEIVE, ADJUST and MOVE, which name no revision, so
  `ck_stock_movements_revision_named` accepts them and `ck_stock_movements_revision_sign`
  leaves their sign alone. Its units are in stock or retired and, its mapping having no
  `revision_id`, leave the column null, which `ck_units_revision_held` accepts. Each new CHECK
  therefore validates on the spot against the rows already there, and a nullable column with no
  default rewrites nothing.
- `downgrade` runs its two UPDATEs first, before it drops the widened status CHECK, so no held
  unit is left in a status the old CHECK forbids: a reserved piece is still on hand, so it goes
  back to `in_stock`; a built one was consumed, as a retired one was adjusted out, so it goes to
  `retired`. Both clear `revision_id`. It deletes no movement, so the ledger keeps the new
  kinds: the runbook's caveat is that the previous release's `wiredex stock rebuild` must not
  run against a ledger holding them (design's decision 6).
- No table is new, so ADR 0007's isolated-tables list is unchanged and there is no
  `isolate_by_workspace` call: row-level security already covers `units` and `stock_movements`,
  and the new column and the new kinds' rows ride the existing policies. Both new indexes lead
  with `workspace_id`, which every query of them filters on.

The four CHECK names go through `op.f()`, which marks a name as already converted so Alembic's
naming convention (`ck_%(table_name)s_%(constraint_name)s`) doesn't run over it a second time.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | None = None
depends_on: str | None = None

_REVISION_ROWS = sa.text("revision_id IS NOT NULL")


def upgrade() -> None:
    # units: two more statuses, and the revision a held unit belongs to (decision 5).
    op.drop_constraint(op.f("ck_units_status"), "units", type_="check")
    op.create_check_constraint(
        op.f("ck_units_status"),
        "units",
        "status IN ('in_stock', 'reserved', 'in_use', 'retired')",
    )
    op.add_column("units", sa.Column("revision_id", sa.Uuid(), nullable=True))
    op.create_check_constraint(
        op.f("ck_units_revision_held"),
        "units",
        "(status IN ('reserved', 'in_use')) = (revision_id IS NOT NULL)",
    )
    op.create_index(
        "ix_units_revision",
        "units",
        ["workspace_id", "revision_id"],
        unique=False,
        postgresql_where=_REVISION_ROWS,
    )

    # stock_movements: the four new kinds name a revision and the other three don't (8.1), and
    # each new kind has its sign (8.2).
    op.create_check_constraint(
        op.f("ck_stock_movements_revision_named"),
        "stock_movements",
        "(kind IN ('RESERVE', 'RELEASE', 'CONSUME', 'RETURN')) = (revision_id IS NOT NULL)",
    )
    op.create_check_constraint(
        op.f("ck_stock_movements_revision_sign"),
        "stock_movements",
        "(kind NOT IN ('RESERVE', 'RETURN') OR change > 0)"
        " AND (kind NOT IN ('RELEASE', 'CONSUME') OR change < 0)",
    )
    op.create_index(
        "ix_stock_movements_revision",
        "stock_movements",
        ["workspace_id", "revision_id"],
        unique=False,
        postgresql_where=_REVISION_ROWS,
    )


def downgrade() -> None:
    # Held units back to the two statuses the previous release knows, their link cleared, before
    # the widened CHECK goes, so the old CHECK holds against every row (decision 6).
    op.execute("UPDATE units SET status = 'in_stock', revision_id = NULL WHERE status = 'reserved'")
    op.execute("UPDATE units SET status = 'retired', revision_id = NULL WHERE status = 'in_use'")

    op.drop_index(
        "ix_stock_movements_revision",
        table_name="stock_movements",
        postgresql_where=_REVISION_ROWS,
    )
    op.drop_constraint(op.f("ck_stock_movements_revision_sign"), "stock_movements", type_="check")
    op.drop_constraint(op.f("ck_stock_movements_revision_named"), "stock_movements", type_="check")

    op.drop_index("ix_units_revision", table_name="units", postgresql_where=_REVISION_ROWS)
    op.drop_constraint(op.f("ck_units_revision_held"), "units", type_="check")
    op.drop_column("units", "revision_id")
    op.drop_constraint(op.f("ck_units_status"), "units", type_="check")
    op.create_check_constraint(
        op.f("ck_units_status"), "units", "status IN ('in_stock', 'retired')"
    )
