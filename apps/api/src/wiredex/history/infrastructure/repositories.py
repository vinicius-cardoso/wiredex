"""History's tables read and cleared with Core queries, each filtered on the workspace before the
policies narrow it too (ADR 0007).

A page costs two statements whatever its size (requirement 8.3): its changes, then their rows,
ranked per change with the record's own row first, at most 20 each, their long values shortened
by `history_trim()` so a source file's text never travels (decision 5).
"""

import typing
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import (
    ColumnElement,
    CursorResult,
    Row,
    Select,
    case,
    delete,
    func,
    literal,
    select,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.selectable import LateralFromClause

from wiredex.history.domain.history import (
    MAX_ROWS_SHOWN,
    RESTORE_REASON,
    Action,
    ActivityFilter,
    Change,
    Operation,
    RecordKind,
    RecordRef,
    RowChange,
    RowKind,
)
from wiredex.history.domain.values import ChangeId, WorkspaceId
from wiredex.history.infrastructure.orm import history_changes, history_entries

# Each tracked table's rows, by the kind history reads them as (decision 2).
ROW_KINDS: Mapping[str, RowKind] = {
    "part_definitions": RowKind.PART,
    "pins": RowKind.PIN,
    "attachments": RowKind.ATTACHMENT,
    "categories": RowKind.CATEGORY,
    "attribute_definitions": RowKind.ATTRIBUTE,
    "locations": RowKind.LOCATION,
    "units": RowKind.UNIT,
    "flashes": RowKind.FLASH,
    "projects": RowKind.PROJECT,
    "revisions": RowKind.REVISION,
    "bom_lines": RowKind.BOM_LINE,
    "bom_designators": RowKind.DESIGNATOR,
    "nets": RowKind.NET,
    "net_pins": RowKind.NET_PIN,
    "firmware": RowKind.FIRMWARE,
    "firmware_versions": RowKind.VERSION,
    "firmware_revisions": RowKind.RUNS_ON,
    "source_files": RowKind.SOURCE_FILE,
}

# Each kind's own table: the row a restore puts back.
ROOT_TABLES: Mapping[RecordKind, str] = {
    RecordKind.PART: "part_definitions",
    RecordKind.UNIT: "units",
    RecordKind.PROJECT: "projects",
    RecordKind.FIRMWARE: "firmware",
    RecordKind.CATEGORY: "categories",
    RecordKind.LOCATION: "locations",
}


class SqlHistoryChanges:
    def __init__(self, session: AsyncSession, workspace_id: WorkspaceId) -> None:
        self._session = session
        self._workspace_id = workspace_id

    async def page(
        self,
        before: ChangeId | None,
        limit: int,
        record: tuple[RecordKind, UUID] | None = None,
        narrowing: ActivityFilter | None = None,
    ) -> list[Change]:
        query = (
            select(history_changes)
            .where(history_changes.c.workspace_id == self._workspace_id)
            .order_by(history_changes.c.id.desc())
            .limit(limit)
        )
        if record is not None:
            kind, record_id = record
            query = query.where(
                history_changes.c.root_kind == kind.value,
                history_changes.c.root_id == record_id,
            )
        if before is not None:
            query = query.where(history_changes.c.id < before)
        if narrowing is not None:
            query = self._narrowed(query, narrowing)
        found = (await self._session.execute(query)).all()
        rows = await self._rows_of([change.id for change in found])
        return [_change(change, rows.get(change.id, ())) for change in found]

    async def own_row(self, change_id: ChangeId) -> tuple[RecordRef, RowChange | None] | None:
        """The change's record, and its first row of the record itself with its whole snapshots,
        in one statement: what a restore puts back, never a shortened value (decision 8)."""
        own = (
            select(history_entries)
            .where(
                history_entries.c.workspace_id == self._workspace_id,
                history_entries.c.change_id == history_changes.c.id,
                history_entries.c.own,
            )
            .order_by(history_entries.c.id)
            .limit(1)
            .lateral("own")
        )
        query = (
            select(
                history_changes.c.root_kind,
                history_changes.c.root_id,
                history_changes.c.root_label,
                own.c.table_name,
                own.c.operation,
                own.c.own,
                own.c.changed,
                own.c.before,
                own.c.after,
            )
            .select_from(history_changes)
            .outerjoin(own, true())
            .where(
                history_changes.c.workspace_id == self._workspace_id,
                history_changes.c.id == change_id,
            )
        )
        found = (await self._session.execute(query)).first()
        if found is None:
            return None
        record = RecordRef(RecordKind(found.root_kind), found.root_id, found.root_label)
        return record, None if found.table_name is None else _row(found)

    async def clear(self) -> int:
        # The rows go with their change: `history_entries.change_id` cascades.
        result = await self._session.execute(
            delete(history_changes).where(history_changes.c.workspace_id == self._workspace_id)
        )
        return typing.cast("CursorResult[Any]", result).rowcount

    def _narrowed(self, query: Select[Any], narrowing: ActivityFilter) -> Select[Any]:
        """The feed's query narrowed as `ActivityFilter.matches` narrows a change: by the root's
        kind, its label holding the text, and the action read off the first own row, which a
        lateral join reads only when an action is asked for."""
        if narrowing.kind is not None:
            query = query.where(history_changes.c.root_kind == narrowing.kind.value)
        if narrowing.text is not None:
            query = query.where(
                history_changes.c.root_label.ilike(_containing(narrowing.text), escape="\\")
            )
        if narrowing.action is None:
            return query
        own = (
            select(
                history_entries.c.operation,
                history_entries.c.changed,
                history_entries.c.before,
                history_entries.c.after,
            )
            .where(
                history_entries.c.workspace_id == self._workspace_id,
                history_entries.c.change_id == history_changes.c.id,
                history_entries.c.own,
            )
            .order_by(history_entries.c.id)
            .limit(1)
            .lateral("own")
        )
        return query.select_from(history_changes.outerjoin(own, true())).where(
            _action_of(own) == narrowing.action.value
        )

    async def _rows_of(self, change_ids: Sequence[int]) -> dict[int, list[RowChange]]:
        """The first rows of each change, its own row first, in one statement."""
        if not change_ids:
            return {}
        rank = (
            func.row_number()
            .over(
                partition_by=history_entries.c.change_id,
                order_by=(history_entries.c.own.desc(), history_entries.c.id),
            )
            .label("rank")
        )
        ranked = (
            select(
                history_entries.c.change_id,
                history_entries.c.table_name,
                history_entries.c.operation,
                history_entries.c.own,
                history_entries.c.changed,
                func.history_trim(history_entries.c.before, type_=JSONB).label("before"),
                func.history_trim(history_entries.c.after, type_=JSONB).label("after"),
                rank,
            )
            .where(
                history_entries.c.workspace_id == self._workspace_id,
                history_entries.c.change_id.in_(change_ids),
            )
            .subquery()
        )
        query = (
            select(ranked)
            .where(ranked.c.rank <= MAX_ROWS_SHOWN)
            .order_by(ranked.c.change_id, ranked.c.rank)
        )
        rows: dict[int, list[RowChange]] = {}
        for entry in (await self._session.execute(query)).all():
            rows.setdefault(entry.change_id, []).append(_row(entry))
        return rows


def _action_of(own: LateralFromClause) -> ColumnElement[str]:
    """`Change.action` in SQL, over the change's first own row: created on an insert, deleted
    on a delete, moved to the trash or back when `trashed_at` changed, restored under the
    `restore` reason, edited otherwise. `trashed_at` changed as `RowChange.changed_names` says:
    listed by the trigger, or, when it listed nothing, its snapshots differ. A change with no own
    row has no operation and no snapshots, so it falls through to the reason."""
    trashed_changed = case(
        (
            own.c.changed.is_not(None),
            literal("trashed_at") == func.any(own.c.changed),
        ),
        else_=own.c.before.op("->")(literal("trashed_at")).is_distinct_from(
            own.c.after.op("->")(literal("trashed_at"))
        ),
    )
    still_trashed = own.c.after.op("->>")(literal("trashed_at")).is_not(None)
    return case(
        (own.c.operation == Operation.INSERT.value, literal(Action.CREATED.value)),
        (own.c.operation == Operation.DELETE.value, literal(Action.DELETED.value)),
        (
            trashed_changed,
            case(
                (still_trashed, literal(Action.MOVED_TO_TRASH.value)),
                else_=literal(Action.RESTORED_FROM_TRASH.value),
            ),
        ),
        (history_changes.c.reason == RESTORE_REASON, literal(Action.RESTORED_VERSION.value)),
        else_=literal(Action.EDITED.value),
    )


def _containing(text: str) -> str:
    """A fragment as a bound ILIKE pattern, `%`, `_` and the escape itself matching themselves."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _change(change: Row[Any], rows: Sequence[RowChange]) -> Change:
    return Change(
        id=ChangeId(change.id),
        occurred_at=change.occurred_at,
        actor_name=change.actor_name,
        reason=change.reason,
        record=RecordRef(RecordKind(change.root_kind), change.root_id, change.root_label),
        rows=tuple(rows),
        row_count=change.entry_count,
    )


def _row(entry: Row[Any]) -> RowChange:
    return RowChange(
        kind=ROW_KINDS[entry.table_name],
        operation=Operation(entry.operation),
        own=entry.own,
        changed=None if entry.changed is None else tuple(entry.changed),
        before=entry.before,
        after=entry.after,
    )
