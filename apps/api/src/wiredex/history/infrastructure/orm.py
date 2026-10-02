"""History's two tables, as migration 0023 creates them (17-history, Data Models).

Only the database writes them, through `record_history()`: the API's role may read and delete,
never insert or update (decision 10 of requirements). They are declared here so the shared
metadata holds the whole schema, which is what keeps `wiredex db check` honest, and so the
repository reads them with Core queries; nothing is mapped to a class, since history is read as
rows, never loaded and changed.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

from wiredex.shared_kernel.infrastructure.orm import metadata

history_changes = Table(
    "history_changes",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("workspace_id", Uuid, nullable=False),
    # `pg_current_xact_id()`: what one transaction wrote to one record is one change.
    Column("transaction_id", BigInteger, nullable=False),
    Column(
        "occurred_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("clock_timestamp()"),
    ),
    # None: Wiredex itself, a job or the command line (decision 4).
    Column("actor_id", Uuid, nullable=True),
    Column("actor_name", Text, nullable=True),
    Column("reason", Text, nullable=True),
    Column("root_kind", Text, nullable=False),
    Column("root_id", Uuid, nullable=False),
    # The record's name as the transaction left it (requirement 1.7).
    Column("root_label", Text, nullable=True),
    Column("entry_count", Integer, nullable=False, server_default=text("1")),
    UniqueConstraint(
        "workspace_id",
        "transaction_id",
        "root_kind",
        "root_id",
        name="uq_history_changes_transaction",
    ),
)

# The feed, newest first, and a record's timeline, newest first (decision 7).
Index("ix_history_changes_feed", history_changes.c.workspace_id, history_changes.c.id.desc())
Index(
    "ix_history_changes_timeline",
    history_changes.c.workspace_id,
    history_changes.c.root_kind,
    history_changes.c.root_id,
    history_changes.c.id.desc(),
)

history_entries = Table(
    "history_entries",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column(
        "change_id",
        BigInteger,
        ForeignKey("history_changes.id", ondelete="CASCADE"),
        nullable=False,
    ),
    # The change's own, kept here too so row-level security filters these rows by themselves.
    Column("workspace_id", Uuid, nullable=False),
    Column("table_name", Text, nullable=False),
    Column("operation", Text, nullable=False),
    # Whether the row is the record's own, not one of what it holds.
    Column("own", Boolean, nullable=False),
    Column("record_id", Uuid, nullable=True),
    # An update's changed fields, compared whole by the trigger.
    Column("changed", ARRAY(Text), nullable=True),
    Column("before", JSONB, nullable=True),
    Column("after", JSONB, nullable=True),
)

Index("ix_history_entries_change_id", history_entries.c.change_id, history_entries.c.id)
