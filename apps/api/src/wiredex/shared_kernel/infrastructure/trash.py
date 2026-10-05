"""The trash in SQL, the same for each of the four tables a record can be moved to the trash in.

A record is in the trash while its `trashed_at` is set (16-soft-delete-and-trash, decision 1). Each
module's repository builds its own statements; these are the pieces they share, so the records
every module answers are ordered and counted the same way the trash merges them (decision 9).
"""

from collections.abc import Iterable

from sqlalchemy import ColumnElement, Select, Table, func

from wiredex.shared_kernel.domain.trash import TrashedSlice


def live(table: Table) -> ColumnElement[bool]:
    """The table's rows that aren't in the trash."""
    return table.c.trashed_at.is_(None)


def in_the_trash(table: Table) -> ColumnElement[bool]:
    """The table's rows in the trash."""
    return table.c.trashed_at.isnot(None)


def trash_newest[E](statement: Select[tuple[E]], table: Table, count: int) -> Select[tuple[E, int]]:
    """The statement narrowed to the table's newest `count` rows in the trash, the id breaking
    ties, over the table's `ix_<table>_trashed`, each row with how many rows match in all.

    The count is a window over the rows the filters keep, which the database works out before
    the limit cuts them: the total comes from the same statement as the rows, so the two always
    agree, and a page costs one statement per table whatever the trash holds.
    """
    newest: Select[tuple[E, int]] = (
        statement.add_columns(func.count().over().label("held"))
        .where(in_the_trash(table))
        .order_by(table.c.trashed_at.desc(), table.c.id.desc())
        .limit(count)
    )
    return newest


def sliced[E](rows: Iterable[tuple[E, int]]) -> TrashedSlice[E]:
    """The rows `trash_newest` answered, as the records and their total: every row carries the
    same total, and no row means nothing matched."""
    found = list(rows)
    return TrashedSlice(tuple(entity for entity, _ in found), found[0][1] if found else 0)
