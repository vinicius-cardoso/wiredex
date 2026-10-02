"""history

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-02 09:05:34.973163

History's schema (17-history, Data Models): every insert, update and delete on eighteen tables is
recorded by the database itself, in the writer's own transaction, so no write path can forget it
and a write that rolls back records nothing (decision 1).

- `history_changes` holds one row per transaction and record: what one save did to one part,
  unit, project, firmware, category or location (decision 3), with when, who and why, read from
  the settings the transaction named next to `app.workspace_id` (decision 4), and the record's
  name as the transaction left it.
- `history_entries` holds each row the change wrote, its whole snapshots before and after, and
  the fields an update changed, compared whole here, since the read side shortens long values.
- `history_root()` knows each tracked table's record: itself, its parent's record, or for an
  attachment its subject's. When the parent is already gone, which only happens while a record is
  deleted with what it holds, the row isn't recorded: the record's own deletion is.
- `record_history()` is the trigger. It runs as the schema owner (`SECURITY DEFINER`, its
  `search_path` fixed), which is what lets the API's role lose `INSERT` and `UPDATE` on both
  tables: history can be read, and deleted by a demo reset, but never forged or edited, as the
  ledger can't be (0011).
- `history_trim()` shortens what the pages read, so a source file's text never fills one.

Purely additive: two tables, three functions and eighteen triggers. The release before this one
writes through the triggers unchanged, naming no user, so after a rollback of the API its writes
are still recorded, as Wiredex's. `downgrade` drops the triggers, then the functions and tables.
Both tables are isolated by workspace (ADR 0007).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from wiredex.shared_kernel.infrastructure.history_tracking import stop_tracking, track_history
from wiredex.shared_kernel.infrastructure.row_security import isolate_by_workspace

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | None = None
depends_on: str | None = None

ROLE = "wiredex_app"

# The tables this migration tracks, spelled out rather than imported: a table tracked later
# needs its own migration, with its branch in `history_root()`.
_TRACKED = (
    "categories",
    "attribute_definitions",
    "part_definitions",
    "pins",
    "attachments",
    "locations",
    "units",
    "projects",
    "revisions",
    "bom_lines",
    "bom_designators",
    "nets",
    "net_pins",
    "firmware",
    "firmware_versions",
    "source_files",
    "firmware_revisions",
    "flashes",
)

_HISTORY_ROOT = """
CREATE FUNCTION history_root(
    p_table text, p_row jsonb,
    OUT root_kind text, OUT root_id uuid, OUT root_label text, OUT own boolean
)
LANGUAGE plpgsql STABLE SET search_path = public, pg_temp AS $$
BEGIN
    own := false;
    CASE p_table
    WHEN 'part_definitions' THEN
        root_kind := 'part'; own := true;
        root_id := (p_row ->> 'id')::uuid; root_label := p_row ->> 'name';
    WHEN 'pins' THEN
        root_kind := 'part';
        SELECT p.id, p.name INTO root_id, root_label
          FROM part_definitions AS p WHERE p.id = (p_row ->> 'part_id')::uuid;
    WHEN 'categories' THEN
        root_kind := 'category'; own := true;
        root_id := (p_row ->> 'id')::uuid; root_label := p_row ->> 'name';
    WHEN 'attribute_definitions' THEN
        root_kind := 'category';
        SELECT c.id, c.name INTO root_id, root_label
          FROM categories AS c WHERE c.id = (p_row ->> 'category_id')::uuid;
    WHEN 'locations' THEN
        root_kind := 'location'; own := true;
        root_id := (p_row ->> 'id')::uuid; root_label := p_row ->> 'name';
    WHEN 'units' THEN
        root_kind := 'unit'; own := true;
        root_id := (p_row ->> 'id')::uuid; root_label := p_row ->> 'code';
    WHEN 'flashes' THEN
        -- A flash keeps its unit's id and code, and outlives a unit deleted for good.
        root_kind := 'unit';
        root_id := (p_row ->> 'unit_id')::uuid; root_label := p_row ->> 'unit_code';
    WHEN 'projects' THEN
        root_kind := 'project'; own := true;
        root_id := (p_row ->> 'id')::uuid; root_label := p_row ->> 'name';
    WHEN 'revisions' THEN
        root_kind := 'project';
        SELECT p.id, p.name INTO root_id, root_label
          FROM projects AS p WHERE p.id = (p_row ->> 'project_id')::uuid;
    WHEN 'bom_lines', 'bom_designators', 'nets', 'net_pins' THEN
        root_kind := 'project';
        SELECT p.id, p.name INTO root_id, root_label
          FROM revisions AS r JOIN projects AS p ON p.id = r.project_id
         WHERE r.id = (p_row ->> 'revision_id')::uuid;
    WHEN 'firmware' THEN
        root_kind := 'firmware'; own := true;
        root_id := (p_row ->> 'id')::uuid; root_label := p_row ->> 'name';
    WHEN 'firmware_versions', 'firmware_revisions' THEN
        root_kind := 'firmware';
        SELECT f.id, f.name INTO root_id, root_label
          FROM firmware AS f WHERE f.id = (p_row ->> 'firmware_id')::uuid;
    WHEN 'source_files' THEN
        root_kind := 'firmware';
        SELECT f.id, f.name INTO root_id, root_label
          FROM firmware_versions AS v JOIN firmware AS f ON f.id = v.firmware_id
         WHERE v.id = (p_row ->> 'version_id')::uuid;
    WHEN 'attachments' THEN
        CASE p_row ->> 'subject_kind'
        WHEN 'part' THEN
            root_kind := 'part';
            SELECT p.id, p.name INTO root_id, root_label
              FROM part_definitions AS p WHERE p.id = (p_row ->> 'subject_id')::uuid;
        WHEN 'project' THEN
            root_kind := 'project';
            SELECT p.id, p.name INTO root_id, root_label
              FROM projects AS p WHERE p.id = (p_row ->> 'subject_id')::uuid;
        WHEN 'revision' THEN
            root_kind := 'project';
            SELECT p.id, p.name INTO root_id, root_label
              FROM revisions AS r JOIN projects AS p ON p.id = r.project_id
             WHERE r.id = (p_row ->> 'subject_id')::uuid;
        ELSE
            NULL;
        END CASE;
    ELSE
        RAISE EXCEPTION 'history_root() knows no table %', p_table;
    END CASE;
END
$$
"""

_RECORD_HISTORY = """
CREATE FUNCTION record_history() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
    v_before jsonb;
    v_after jsonb;
    v_row jsonb;
    v_changed text[];
    v_root record;
    v_workspace uuid;
    v_change bigint;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        v_before := to_jsonb(OLD);
    END IF;
    IF TG_OP <> 'DELETE' THEN
        v_after := to_jsonb(NEW);
    END IF;
    v_row := coalesce(v_after, v_before);
    IF TG_OP = 'UPDATE' THEN
        -- Compared whole: the read side shortens long values. When the row was last updated
        -- says nothing on its own (requirement 1.3).
        SELECT coalesce(array_agg(fields.key ORDER BY fields.key), '{}')
          INTO v_changed
          FROM jsonb_each(v_after) AS fields
         WHERE fields.key <> 'updated_at'
           AND fields.value IS DISTINCT FROM v_before -> fields.key;
        IF cardinality(v_changed) = 0 THEN
            RETURN NULL;
        END IF;
    END IF;
    SELECT * INTO v_root FROM history_root(TG_TABLE_NAME, v_row);
    IF v_root.root_id IS NULL THEN
        -- Its parent went in this very statement: a record deleted with what it holds, whose
        -- own deletion is recorded (requirement 1.5).
        RETURN NULL;
    END IF;
    v_workspace := (v_row ->> 'workspace_id')::uuid;
    INSERT INTO history_changes AS c (
        workspace_id, transaction_id, actor_id, actor_name, reason,
        root_kind, root_id, root_label
    ) VALUES (
        v_workspace,
        pg_current_xact_id()::text::bigint,
        nullif(current_setting('app.user_id', true), '')::uuid,
        nullif(current_setting('app.user_name', true), ''),
        nullif(current_setting('app.change_reason', true), ''),
        v_root.root_kind, v_root.root_id, v_root.root_label
    )
    ON CONFLICT ON CONSTRAINT uq_history_changes_transaction DO UPDATE
        SET entry_count = c.entry_count + 1, root_label = excluded.root_label
    RETURNING c.id INTO v_change;
    INSERT INTO history_entries (
        change_id, workspace_id, table_name, operation, own, record_id, changed, before, after
    ) VALUES (
        v_change, v_workspace, TG_TABLE_NAME, lower(TG_OP), v_root.own,
        (v_row ->> 'id')::uuid, v_changed, v_before, v_after
    );
    RETURN NULL;
END
$$
"""

_HISTORY_TRIM = """
CREATE FUNCTION history_trim(p_snapshot jsonb) RETURNS jsonb
LANGUAGE sql IMMUTABLE SET search_path = public, pg_temp AS $$
    SELECT jsonb_object_agg(
        fields.key,
        CASE
            WHEN jsonb_typeof(fields.value) = 'string' AND length(fields.value #>> '{}') > 300
                THEN to_jsonb(left(fields.value #>> '{}', 300) || '…')
            WHEN jsonb_typeof(fields.value) IN ('object', 'array')
                 AND length(fields.value::text) > 300
                THEN to_jsonb(left(fields.value::text, 300) || '…')
            ELSE fields.value
        END
    )
    FROM jsonb_each(p_snapshot) AS fields
$$
"""


def upgrade() -> None:
    op.create_table(
        "history_changes",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("transaction_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("actor_name", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("root_kind", sa.Text(), nullable=False),
        sa.Column("root_id", sa.Uuid(), nullable=False),
        sa.Column("root_label", sa.Text(), nullable=True),
        sa.Column("entry_count", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_history_changes")),
        sa.UniqueConstraint(
            "workspace_id",
            "transaction_id",
            "root_kind",
            "root_id",
            name="uq_history_changes_transaction",
        ),
    )
    op.create_index(
        "ix_history_changes_feed",
        "history_changes",
        ["workspace_id", sa.literal_column("id DESC")],
        unique=False,
    )
    op.create_index(
        "ix_history_changes_timeline",
        "history_changes",
        ["workspace_id", "root_kind", "root_id", sa.literal_column("id DESC")],
        unique=False,
    )
    op.create_table(
        "history_entries",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("change_id", sa.BigInteger(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("table_name", sa.Text(), nullable=False),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("own", sa.Boolean(), nullable=False),
        sa.Column("record_id", sa.Uuid(), nullable=True),
        sa.Column("changed", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["change_id"],
            ["history_changes.id"],
            name=op.f("fk_history_entries_change_id_history_changes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_history_entries")),
    )
    op.create_index(
        "ix_history_entries_change_id", "history_entries", ["change_id", "id"], unique=False
    )
    for table in ("history_changes", "history_entries"):
        isolate_by_workspace(op.execute, table)
        # 0004's default privileges granted these; only the trigger, as the owner, writes.
        op.execute(f"REVOKE INSERT, UPDATE ON {table} FROM {ROLE}")
    op.execute(_HISTORY_ROOT)
    op.execute(_HISTORY_TRIM)
    op.execute(_RECORD_HISTORY)
    for table in _TRACKED:
        track_history(op.execute, table)


def downgrade() -> None:
    for table in reversed(_TRACKED):
        stop_tracking(op.execute, table)
    op.execute("DROP FUNCTION record_history()")
    op.execute("DROP FUNCTION history_trim(jsonb)")
    op.execute("DROP FUNCTION history_root(text, jsonb)")
    op.drop_index("ix_history_entries_change_id", table_name="history_entries")
    op.drop_table("history_entries")
    op.drop_index("ix_history_changes_timeline", table_name="history_changes")
    op.drop_index("ix_history_changes_feed", table_name="history_changes")
    op.drop_table("history_changes")
