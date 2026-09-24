"""Baseline: an empty schema, so every later migration has a parent.

Revision ID: 0001
Revises:
Create Date: 2026-09-23
"""

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    pass  # The identity tables arrive in 0002.


def downgrade() -> None:
    pass
