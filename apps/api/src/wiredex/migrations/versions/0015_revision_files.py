"""revision files

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-28 14:10:00.000000

A revision's Gerbers travel as a ZIP, and its schematic and Gerbers are kinds of their own, so
two CHECKs `0007` created are dropped and created again, wider: `ck_files_media_type` with
`application/zip`, and `ck_attachments_attachment_kind` with `schematic` and `gerbers`.
Written by hand: autogenerate doesn't compare CHECK constraints.

Only widening, so the release before this one keeps working against the schema. It reads no
ZIP and no row of the two new kinds until one is uploaded, which a failed deploy's rollback
comes well before.

`downgrade` makes the rows fit the narrower CHECKs first: schematic and Gerbers attachments
become `other`, the attachments of ZIP files are deleted, and then the ZIP file rows, which
the attachments' `RESTRICT` key would otherwise hold in place. The stored objects are left to
the nightly prune's store sweep; the migration never reaches the file store.
"""

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | None = None
depends_on: str | None = None

MEDIA_TYPE = "ck_files_media_type"
KIND = "ck_attachments_attachment_kind"

MEDIA_TYPES = ("application/pdf", "image/png", "image/jpeg", "image/webp")
KINDS = ("datasheet", "image", "pinout_diagram", "other")


def _in(column: str, values: tuple[str, ...]) -> str:
    listed = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({listed})"


def _replace(name: str, table: str, condition: str) -> None:
    op.drop_constraint(op.f(name), table, type_="check")
    op.create_check_constraint(op.f(name), table, condition)


def upgrade() -> None:
    _replace(MEDIA_TYPE, "files", _in("media_type", (*MEDIA_TYPES, "application/zip")))
    _replace(KIND, "attachments", _in("kind", (*KINDS[:-1], "schematic", "gerbers", "other")))


def downgrade() -> None:
    op.execute("UPDATE attachments SET kind = 'other' WHERE kind IN ('schematic', 'gerbers')")
    op.execute(
        "DELETE FROM attachments USING files"
        " WHERE files.workspace_id = attachments.workspace_id"
        " AND files.sha256 = attachments.sha256"
        " AND files.media_type = 'application/zip'"
    )
    op.execute("DELETE FROM files WHERE media_type = 'application/zip'")
    _replace(KIND, "attachments", _in("kind", KINDS))
    _replace(MEDIA_TYPE, "files", _in("media_type", MEDIA_TYPES))
