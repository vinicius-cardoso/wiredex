"""firmware builds

Revision ID: 0024
Revises: 0023
Create Date: 2026-10-09 22:10:00.000000

A released firmware version keeps its builds as attachments (20-firmware-builds), so two CHECKs
are dropped and created again, wider: `ck_attachments_subject_kind` with `firmware_version`, and
`ck_attachments_attachment_kind` with `firmware_build`. Written by hand: autogenerate doesn't
compare CHECK constraints.

Only widening, so the release before this one keeps working against the schema: it writes
neither value and lists no attachment of a version.

`downgrade` deletes the builds first, since the narrower CHECKs have no place for them. Their
file rows and stored objects are left to the nightly prune, which removes a file no attachment
names; the migration never reaches the file store.
"""

from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | None = None
depends_on: str | None = None

SUBJECT = "ck_attachments_subject_kind"
KIND = "ck_attachments_attachment_kind"

SUBJECTS = ("part", "project", "revision")
KINDS = ("datasheet", "image", "pinout_diagram", "schematic", "gerbers", "other")


def _in(column: str, values: tuple[str, ...]) -> str:
    listed = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({listed})"


def _replace(name: str, condition: str) -> None:
    op.drop_constraint(op.f(name), "attachments", type_="check")
    op.create_check_constraint(op.f(name), "attachments", condition)


def upgrade() -> None:
    _replace(SUBJECT, _in("subject_kind", (*SUBJECTS, "firmware_version")))
    _replace(KIND, _in("kind", (*KINDS, "firmware_build")))


def downgrade() -> None:
    op.execute(
        "DELETE FROM attachments WHERE subject_kind = 'firmware_version' OR kind = 'firmware_build'"
    )
    _replace(KIND, _in("kind", KINDS))
    _replace(SUBJECT, _in("subject_kind", SUBJECTS))
