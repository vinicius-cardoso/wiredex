"""firmware git link

Revision ID: 0027
Revises: 0026
Create Date: 2026-10-11 02:00:00.000000

A firmware can say where its code lives and a version which commit it was cut from
(22-firmware-git-link): `firmware.repository` holds the address of the repository's page and
`firmware_versions.commit_sha` the commit's object name. The second column isn't called
`commit`, which is a word of SQL.

Both are nullable and have no default, so the release before this one keeps working against
the schema: it neither reads nor writes them, and the rows it inserts hold none.

`downgrade` drops both columns, and with them the links typed since; nothing else refers to
them.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("firmware", sa.Column("repository", sa.String(500), nullable=True))
    op.add_column("firmware_versions", sa.Column("commit_sha", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("firmware_versions", "commit_sha")
    op.drop_column("firmware", "repository")
