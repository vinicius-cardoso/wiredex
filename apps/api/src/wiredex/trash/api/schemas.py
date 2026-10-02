"""What the trash gives over HTTP, in primitives only: no domain object reaches a field, and the
`from_*` classmethods do the converting, as every module's schemas do."""

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel

from wiredex.trash.domain.trash import TrashedItem, TrashKind, TrashPage

# The kinds spelled out for the wire, so the generated client gets a union it can switch on. A
# test keeps this list in step with `TrashKind`, as the other modules do for their enums.
type TrashKindName = Literal["part", "unit", "project", "firmware"]


class TrashedItemResponse(BaseModel):
    """One record in the trash, as the trash page lists it (requirement 4.1): `name` is a unit's
    code, and `detail` a part's MPN, a unit's part or a firmware's target, when it has one."""

    kind: TrashKindName
    id: UUID
    name: str
    detail: str | None
    trashed_at: datetime

    @classmethod
    def from_item(cls, item: TrashedItem) -> Self:
        return cls(
            kind=kind_name(item.kind),
            id=item.id,
            name=item.name,
            detail=item.detail,
            trashed_at=item.trashed_at,
        )


class TrashPageResponse(BaseModel):
    """A page of the trash, newest first, and the cursor reading the next one, or None on the
    last page (requirements 4.2, 4.3)."""

    items: list[TrashedItemResponse]
    next_cursor: str | None

    @classmethod
    def from_page(cls, page: TrashPage) -> Self:
        return cls(
            items=[TrashedItemResponse.from_item(item) for item in page.items],
            next_cursor=None if page.next is None else page.next.encode(),
        )


def kind_name(kind: TrashKind) -> TrashKindName:
    # mypy reads an enum's value as the literals its members hold, so a fifth kind stops
    # type-checking here until the wire contract above lists it too.
    name: TrashKindName = kind.value
    return name
