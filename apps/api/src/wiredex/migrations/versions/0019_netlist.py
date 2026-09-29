"""netlist

Revision ID: 0019
Revises: 0018
Create Date: 2026-09-29 15:00:00.000000

A revision's netlist: `nets`, one row per net, and `net_pins`, one row per pin reference a net
connects (11-netlist-editor, Data Models). Both are workspace-scoped, so both end with
`isolate_by_workspace`: the API connects as `wiredex_app`, which row-level security applies
to, and migrations run as the owner, which it doesn't (ADR 0007).

Details worth knowing when reading the DDL:

- A net points at its revision by `(workspace_id, revision_id)`, against 0017's
  `uq_revisions_workspace_id`, and a reference at its net by `(workspace_id, revision_id,
  net_id)`, against `uq_nets_workspace_id`: Postgres checks foreign keys without row-level
  security, so the pairs are what refuse a row filed under another workspace's revision.
- A reference is a designator and a pin number as text, with no foreign key to
  `bom_designators` or `pins` (decision 2): a BOM or pinout edit leaves it standing, to read as
  unresolved. The CHECKs hold both to their canonical forms, so a join on them never folds.
- The primary key makes a pin once per net; nothing is said across nets, which 12 reports.
  `ix_net_pins_reference` is 12's too: a revision's references grouped across its nets, and
  every net on one part's pin.
- Names are unique per revision folded, `uq_nets_name` on `lower(name)`, as 08's are.
- Deleting cascades, and nothing else does: a revision takes its nets, a net its references.

Purely additive: two new tables, so the release before this one keeps working against the
schema. `downgrade` drops `net_pins`, then `nets`; DROP TABLE takes the indexes and the
policies with it, so the round trip (up, down, up) is clean.
"""

import sqlalchemy as sa
from alembic import op

from wiredex.shared_kernel.infrastructure.row_security import isolate_by_workspace

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | None = None
depends_on: str | None = None

ISOLATED = ("nets", "net_pins")
WIRE_COLORS = (
    "black",
    "brown",
    "red",
    "orange",
    "yellow",
    "green",
    "blue",
    "violet",
    "grey",
    "white",
)


def upgrade() -> None:
    op.create_table(
        "nets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.Column(
            "color",
            sa.Enum(
                *WIRE_COLORS, name="color", native_enum=False, create_constraint=True, length=8
            ),
            nullable=True,
        ),
        sa.Column("notes", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "revision_id"],
            ["revisions.workspace_id", "revisions.id"],
            name=op.f("fk_nets_workspace_id_revisions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_nets")),
        sa.UniqueConstraint("workspace_id", "revision_id", "id", name=op.f("uq_nets_workspace_id")),
    )
    op.create_index(op.f("ix_nets_workspace_id"), "nets", ["workspace_id"], unique=False)
    op.create_index(
        "uq_nets_name",
        "nets",
        ["workspace_id", "revision_id", sa.literal_column("lower(name)")],
        unique=True,
    )
    op.create_table(
        "net_pins",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("net_id", sa.Uuid(), nullable=False),
        sa.Column("designator", sa.String(length=12), nullable=False),
        sa.Column("pin", sa.String(length=16), nullable=False),
        sa.CheckConstraint(
            "designator ~ '^[A-Z]{1,8}[1-9][0-9]{0,3}$'",
            name=op.f("ck_net_pins_canonical_designator"),
        ),
        sa.CheckConstraint("pin ~ '^[A-Z0-9_.+-]{1,16}$'", name=op.f("ck_net_pins_canonical_pin")),
        sa.ForeignKeyConstraint(
            ["workspace_id", "revision_id", "net_id"],
            ["nets.workspace_id", "nets.revision_id", "nets.id"],
            name=op.f("fk_net_pins_workspace_id_nets"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id", "net_id", "designator", "pin", name=op.f("pk_net_pins")
        ),
    )
    op.create_index(
        "ix_net_pins_reference",
        "net_pins",
        ["workspace_id", "revision_id", "designator", "pin"],
        unique=False,
    )
    for table in ISOLATED:
        isolate_by_workspace(op.execute, table)


def downgrade() -> None:
    # References first, whose key holds the nets' triple in place. DROP TABLE takes each
    # table's indexes and policy with it.
    op.drop_table("net_pins")
    op.drop_table("nets")
