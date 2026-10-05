"""The trash over HTTP: one list across the four kinds, a restore, a delete for good, and
emptying it (16-soft-delete-and-trash, HTTP).

A factory, as the other routers are: the use cases and the workspace dependency come in as
arguments, so the composition root decides what runs. The trash never imports identity or the
modules whose records it holds: `bootstrap/app.py` builds `current_workspace` from the session
use cases, and `bootstrap/trash.py` builds a bin per kind over each module's use cases. Every
write is a POST or a DELETE, so a cookie session carries the CSRF header for it (ADR 0008),
which the auth test covers.
"""

from collections.abc import Awaitable, Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from wiredex.shared_kernel.api.paging import PageNumber, PageSize
from wiredex.shared_kernel.domain.paging import DEFAULT_PAGE_SIZE, PageRequest
from wiredex.trash.api.schemas import TrashKindName, TrashPageResponse
from wiredex.trash.application.trash import (
    DeleteFromTrash,
    EmptyTrash,
    ListTrash,
    RestoreFromTrash,
)
from wiredex.trash.domain.errors import TrashError, TrashItemNotFoundError
from wiredex.trash.domain.trash import MAX_FILTER_TEXT_LENGTH, TrashFilter, TrashKind
from wiredex.trash.domain.values import WorkspaceId


@dataclass(frozen=True, slots=True)
class TrashUseCases:
    list_trash: ListTrash
    restore_from_trash: RestoreFromTrash
    delete_from_trash: DeleteFromTrash
    empty_trash: EmptyTrash


type CurrentWorkspaceDependency = Callable[[Request], Awaitable[WorkspaceId]]

# The design's Error Handling: a record not in the trash, another bench's included, is a 404, so
# an id says nothing about another workspace; anything else the trash refuses is the request's
# content being unprocessable.
_STATUS_BY_ERROR: Mapping[type[TrashError], int] = {
    TrashItemNotFoundError: status.HTTP_404_NOT_FOUND,
}


def create_router(
    use_cases: TrashUseCases, current_workspace: CurrentWorkspaceDependency
) -> APIRouter:
    router = APIRouter(prefix="/trash", tags=["trash"])

    @router.get("")
    async def list_trash(
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
        page: PageNumber = 1,
        page_size: PageSize = DEFAULT_PAGE_SIZE,
        kind: TrashKindName | None = None,
        q: Annotated[str | None, Query(max_length=MAX_FILTER_TEXT_LENGTH)] = None,
    ) -> TrashPageResponse:
        """A page of the trash, newest first by when each record moved there, with how many
        records there are in all; only one kind's records when `kind` names it, and only those
        whose name or detail holds `q`, case aside. A page past the end answers the last one,
        and `page` says which (requirements 4.1 to 4.5)."""
        with _refusals():
            narrowing = TrashFilter(None if kind is None else TrashKind(kind), q)
            found = await use_cases.list_trash(
                workspace_id, PageRequest(page, page_size), narrowing
            )
        return TrashPageResponse.from_page(found)

    @router.delete("", status_code=status.HTTP_204_NO_CONTENT)
    async def empty_trash(
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> None:
        """Every record in the trash deleted for good, one kind after the other (6.4)."""
        await use_cases.empty_trash(workspace_id)

    @router.post("/{kind}/{item_id}/restore", status_code=status.HTTP_204_NO_CONTENT)
    async def restore_from_trash(
        kind: TrashKindName,
        item_id: UUID,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> None:
        """The record back with its contents, as it was; 404 for one that isn't in the trash,
        another bench's included (requirements 5.1 to 5.3)."""
        with _refusals():
            await use_cases.restore_from_trash(workspace_id, TrashKind(kind), item_id)

    @router.delete("/{kind}/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_from_trash(
        kind: TrashKindName,
        item_id: UUID,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> None:
        """The record deleted for good with its contents; 404 for one that isn't in the trash,
        another bench's included (requirements 6.1 to 6.3)."""
        with _refusals():
            await use_cases.delete_from_trash(workspace_id, TrashKind(kind), item_id)

    return router


@contextmanager
def _refusals() -> Iterator[None]:
    """Turns a trash refusal into the status the design's table gives it, as the other routers'
    `_refusals` do: the mapping is this router's contract, not the application's."""
    try:
        yield
    except TrashError as error:
        status_code = _STATUS_BY_ERROR.get(type(error), status.HTTP_422_UNPROCESSABLE_CONTENT)
        raise HTTPException(status_code, str(error)) from error
