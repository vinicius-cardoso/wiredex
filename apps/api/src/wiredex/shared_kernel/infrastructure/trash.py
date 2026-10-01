"""The trash in SQL, the same for each of the four tables a record can be moved to the trash in.

A record is in the trash while its `trashed_at` is set (16-soft-delete-and-trash, decision 1). Each
module's repository builds its own statements; these are the pieces they share, so the page every
module answers is ordered and cut the same way the trash merges them (decision 9).
"""

from sqlalchemy import ColumnElement, Select, Table, literal, tuple_

from wiredex.shared_kernel.domain.trash import TrashPosition


def live(table: Table) -> ColumnElement[bool]:
    """The table's rows that aren't in the trash."""
    return table.c.trashed_at.is_(None)


def in_the_trash(table: Table) -> ColumnElement[bool]:
    """The table's rows in the trash."""
    return table.c.trashed_at.isnot(None)


def trash_page[T: tuple[object, ...]](
    statement: Select[T], table: Table, before: TrashPosition | None, limit: int
) -> Select[T]:
    """The statement narrowed to one page of the table's trash: newest first, the id breaking
    ties, from the position on, at most `limit` rows, over the table's `ix_<table>_trashed`.

    The bound values carry the columns' own types, so a time keeps its offset on the way in.
    """
    page = (
        statement.where(in_the_trash(table))
        .order_by(table.c.trashed_at.desc(), table.c.id.desc())
        .limit(limit)
    )
    if before is None:
        return page
    position = tuple_(
        literal(before.trashed_at, table.c.trashed_at.type), literal(before.id, table.c.id.type)
    )
    return page.where(tuple_(table.c.trashed_at, table.c.id) < position)
