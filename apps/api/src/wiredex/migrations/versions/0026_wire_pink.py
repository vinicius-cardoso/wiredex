"""wire pink

Revision ID: 0026
Revises: 0025
Create Date: 2026-10-11 00:30:00.000000

Pink joins the colours a net's wire may have, so `ck_nets_color`, the CHECK `0019` created over
the ten of the resistor code, is dropped and created again with it. Written by hand:
autogenerate doesn't compare CHECK constraints.

Only widening, so the release before this one keeps working against the schema: it writes no
pink net and reads a net's colour as text.

`downgrade` clears the colour of the nets that are pink, since the narrower CHECK has no place
for it, and leaves the nets themselves and their pins as they are.
"""

from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | None = None
depends_on: str | None = None

CHECK = "ck_nets_color"
COLORS = ("black", "brown", "red", "orange", "yellow", "green", "blue", "violet", "grey", "white")


def _in(values: tuple[str, ...]) -> str:
    listed = ", ".join(f"'{value}'" for value in values)
    return f"color IN ({listed})"


def upgrade() -> None:
    op.drop_constraint(op.f(CHECK), "nets", type_="check")
    op.create_check_constraint(op.f(CHECK), "nets", _in((*COLORS, "pink")))


def downgrade() -> None:
    op.execute("UPDATE nets SET color = NULL WHERE color = 'pink'")
    op.drop_constraint(op.f(CHECK), "nets", type_="check")
    op.create_check_constraint(op.f(CHECK), "nets", _in(COLORS))
