"""workspace settings

Revision ID: 0029
Revises: 0028
Create Date: 2026-10-11 18:00:00.000000

`workspace_preferences` gains the settings of 25-workspace-settings:

- `default_minimum_stock`, nullable, 0 to 1,000,000: a part's minimum when neither it nor its
  categories set one.
- `code_prefix`, `'WX'` by default, a letter then up to five letters or digits: what new short
  codes start with.
- `date_format` and `number_format`, `'language'` by default, each a CHECKed choice.
- `trash_retention_days`, nullable, 1 to 3,650: how long the nightly sweep leaves a record in
  the trash.

Every column is nullable or has a server default, so the release before this one, which inserts
a row with the stock basis alone, keeps working.

`downgrade` drops the columns, and with them the choices saved since.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | None = None
depends_on: str | None = None

TABLE = "workspace_preferences"
CHECKS = {
    "default_minimum_stock_range": (
        "default_minimum_stock >= 0 AND default_minimum_stock <= 1000000"
    ),
    "code_prefix_shape": "code_prefix ~ '^[A-Z][A-Z0-9]{0,5}$'",
    "date_format": "date_format IN ('language', 'iso', 'dmy', 'mdy')",
    "number_format": "number_format IN ('language', 'point', 'comma')",
    "trash_retention_days_range": "trash_retention_days >= 1 AND trash_retention_days <= 3650",
}


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("default_minimum_stock", sa.Integer(), nullable=True))
    op.add_column(
        TABLE, sa.Column("code_prefix", sa.String(6), nullable=False, server_default="WX")
    )
    for column in ("date_format", "number_format"):
        op.add_column(
            TABLE, sa.Column(column, sa.String(16), nullable=False, server_default="language")
        )
    op.add_column(TABLE, sa.Column("trash_retention_days", sa.Integer(), nullable=True))
    for name, condition in CHECKS.items():
        op.create_check_constraint(op.f(f"ck_{TABLE}_{name}"), TABLE, condition)


def downgrade() -> None:
    for name in CHECKS:
        op.drop_constraint(op.f(f"ck_{TABLE}_{name}"), TABLE, type_="check")
    for column in (
        "trash_retention_days",
        "number_format",
        "date_format",
        "code_prefix",
        "default_minimum_stock",
    ):
        op.drop_column(TABLE, column)
