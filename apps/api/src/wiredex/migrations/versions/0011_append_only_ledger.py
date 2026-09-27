"""append-only ledger

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-27 12:00:00.000000

The stock ledger is append-only (ADR 0002): a movement is never rewritten, a correction is
a new movement. Until now only the code kept that promise; the API's role could still
UPDATE a movement. This takes that right away, so the database refuses it even from a bug.
DELETE stays: a demo reset clears a guest's ledger, and a lot's deletion cascades to its
movements.
"""

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | None = None
depends_on: str | None = None

ROLE = "wiredex_app"


def upgrade() -> None:
    op.execute(f"REVOKE UPDATE ON stock_movements FROM {ROLE}")


def downgrade() -> None:
    op.execute(f"GRANT UPDATE ON stock_movements TO {ROLE}")
