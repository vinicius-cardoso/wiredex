"""A record's place in the trash, and a module's share of it, in words every module and the
trash share.

The trash lists records of four modules in one order (16-soft-delete-and-trash, decision 9). Each
module's repository answers its own newest records and how many it holds, and the trash module
merges them; these values are what both sides speak, so neither imports the other.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True, order=True)
class TrashPosition:
    """When a record was moved to the trash, and its id, which breaks ties.

    Ordered field by field, the time first: the trash reads newest first, so the records are
    sorted on this, descending. Ids are UUIDv7 and unique across tables, so two records of two
    kinds moved in the same instant still order one way.
    """

    trashed_at: datetime
    id: UUID


@dataclass(frozen=True, slots=True)
class TrashedSlice[T]:
    """A module's newest records in the trash that match, and how many match in all."""

    items: tuple[T, ...]
    total: int
