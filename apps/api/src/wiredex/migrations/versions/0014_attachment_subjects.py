"""attachment subjects

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-28 12:53:18.062711

An attachment may now belong to a project (its photos) or a revision (its files) as well as a
part, so `ck_attachments_subject_kind`, the CHECK `0007` created over `part` alone, is dropped
and created again over `part`, `project` and `revision`. Written by hand: autogenerate doesn't
compare CHECK constraints, so `make migration` gave an empty file.

Only widening, so the release before this one keeps working against the schema. It reads no
row of the two new kinds until a photo or a revision file exists, which a failed deploy's
rollback comes well before.

`downgrade` deletes the attachments of projects and revisions first, since the narrower CHECK
would refuse them. Their file rows, then unused, and the stored objects are left to the
nightly prune, as a detached part's are; the migration never reaches the file store.
"""

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | None = None
depends_on: str | None = None

CHECK = "ck_attachments_subject_kind"


def upgrade() -> None:
    op.drop_constraint(op.f(CHECK), "attachments", type_="check")
    op.create_check_constraint(
        op.f(CHECK), "attachments", "subject_kind IN ('part', 'project', 'revision')"
    )


def downgrade() -> None:
    op.execute("DELETE FROM attachments WHERE subject_kind IN ('project', 'revision')")
    op.drop_constraint(op.f(CHECK), "attachments", type_="check")
    op.create_check_constraint(op.f(CHECK), "attachments", "subject_kind IN ('part')")
