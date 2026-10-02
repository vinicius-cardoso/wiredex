"""History in Postgres: which tables record their changes, and attaching the trigger that does
(17-history, decision 1).

Migration `0023` defines `record_history()`, the one trigger function, and `history_root()`, which
knows each tracked table's record. A table is tracked once its migration calls `track_history`,
and a table tracked later needs its branch in `history_root()` too, replaced in that migration.

Migrations that already ran depend on these statements: don't change what they do.
"""

from collections.abc import Callable

type Execute = Callable[[str], object]

TRIGGER = "record_history"

# Every table whose rows history records, in the order migration 0023 tracked them (decision 2).
TRACKED_TABLES: tuple[str, ...] = (
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


def track_history(execute: Execute, table: str) -> None:
    """Record every insert, update and delete on TABLE, in the writer's own transaction.

    In a migration: `track_history(op.execute, "parts")`. The table needs a `workspace_id`
    column, and a branch in `history_root()`.
    """
    execute(
        f"CREATE TRIGGER {TRIGGER} AFTER INSERT OR UPDATE OR DELETE ON {table}"
        f" FOR EACH ROW EXECUTE FUNCTION {TRIGGER}()"
    )


def stop_tracking(execute: Execute, table: str) -> None:
    """Undo `track_history`, for a migration's downgrade."""
    execute(f"DROP TRIGGER IF EXISTS {TRIGGER} ON {table}")
