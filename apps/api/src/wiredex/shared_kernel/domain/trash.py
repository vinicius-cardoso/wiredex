"""Where a page of the trash stops, in words every module and the trash share.

The trash lists records of four modules in one order (16-soft-delete-and-trash, decision 9). Each
module's repository pages its own records from a position, and the trash module merges the pages;
this value is what both sides speak, so neither imports the other.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True, order=True)
class TrashPosition:
    """When a record was moved to the trash, and its id, which breaks ties.

    Ordered field by field, the time first: the trash reads newest first, so a page holds the
    records *before* a position. Ids are UUIDv7 and unique across tables, so two records of two
    kinds moved in the same instant still order one way.
    """

    trashed_at: datetime
    id: UUID
