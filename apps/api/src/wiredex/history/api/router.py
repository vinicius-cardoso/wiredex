"""History over HTTP: the workspace's activity feed, a record's timeline, and restoring a
change (17-history, HTTP).

A factory, as the other routers are: the use cases and the workspace dependency come in as
arguments, so the composition root decides what runs. History never imports identity or the
modules whose records it is about: `bootstrap/app.py` builds `current_workspace` from the session
use cases, and `bootstrap/history.py` answers whether a record is live through its module.
"""

from collections.abc import Awaitable, Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status

from wiredex.history.api.schemas import (
    ActionName,
    HistoryPageResponse,
    RecordKindName,
    TimelineKindName,
)
from wiredex.history.application.history import ListActivity, ListTimeline, RestoreVersion
from wiredex.history.domain.errors import (
    ChangeNotFoundError,
    HistoryError,
    NotRestorableError,
    RecordNotFoundError,
)
from wiredex.history.domain.history import (
    MAX_FILTER_TEXT_LENGTH,
    Action,
    ActivityFilter,
    RecordKind,
)
from wiredex.history.domain.values import ChangeId, WorkspaceId
from wiredex.shared_kernel.api.paging import PageNumber, PageSize
from wiredex.shared_kernel.domain.paging import DEFAULT_PAGE_SIZE, PageRequest


@dataclass(frozen=True, slots=True)
class HistoryUseCases:
    list_activity: ListActivity
    list_timeline: ListTimeline
    restore_version: RestoreVersion


type CurrentWorkspaceDependency = Callable[[Request], Awaitable[WorkspaceId]]

# The design's Error Handling: what isn't the workspace's is a 404, so an id says nothing about
# another bench; a change that can't be restored is a 409; anything else history refuses is the
# request's content being unprocessable.
_STATUS_BY_ERROR: Mapping[type[HistoryError], int] = {
    ChangeNotFoundError: status.HTTP_404_NOT_FOUND,
    RecordNotFoundError: status.HTTP_404_NOT_FOUND,
    NotRestorableError: status.HTTP_409_CONFLICT,
}

# A change id is a positive bigint (decision 7).
_MAX_CHANGE_ID = 2**63 - 1


def create_router(
    use_cases: HistoryUseCases, current_workspace: CurrentWorkspaceDependency
) -> APIRouter:
    router = APIRouter(prefix="/history", tags=["history"])

    @router.get("")
    async def list_activity(
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
        narrowing: Annotated[ActivityFilter, Depends(_activity_filter)],
        page: PageNumber = 1,
        page_size: PageSize = DEFAULT_PAGE_SIZE,
    ) -> HistoryPageResponse:
        """A page of the workspace's changes, newest first, with how many there are in all;
        only those that did `action`, to a record of `kind`, whose name as the change left it
        holds `q`, case aside, when asked. A page past the end answers the last one, and `page`
        says which (requirements 2.1 to 2.6)."""
        with _refusals():
            found = await use_cases.list_activity(
                workspace_id, PageRequest(page, page_size), narrowing
            )
        return HistoryPageResponse.from_page(found)

    @router.get("/{kind}/{record_id}")
    async def list_timeline(
        kind: TimelineKindName,
        record_id: UUID,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
        page: PageNumber = 1,
        page_size: PageSize = DEFAULT_PAGE_SIZE,
    ) -> HistoryPageResponse:
        """A page of a part's, unit's, project's or firmware's changes, those to what it holds
        included, newest first, with how many there are in all; 404 for a record that isn't
        live in the workspace (requirement 3)."""
        with _refusals():
            record = (RecordKind(kind), record_id)
            found = await use_cases.list_timeline(
                workspace_id, record, PageRequest(page, page_size)
            )
        return HistoryPageResponse.from_page(found)

    @router.post("/changes/{change_id}/restore", status_code=status.HTTP_204_NO_CONTENT)
    async def restore_version(
        change_id: Annotated[int, Path(ge=1, le=_MAX_CHANGE_ID)],
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> None:
        """Puts the change's record back as it was just before the change, through the record's
        own edit, recorded as a new change; a move to the trash is restored from the trash.
        404 for a change the workspace doesn't hold, 409 for one that can't be restored or a
        restore the record's module refuses, with its sentence (requirement 4)."""
        with _refusals():
            await use_cases.restore_version(workspace_id, ChangeId(change_id))

    return router


async def _activity_filter(
    action: ActionName | None = None,
    kind: RecordKindName | None = None,
    q: Annotated[str | None, Query(max_length=MAX_FILTER_TEXT_LENGTH)] = None,
) -> ActivityFilter:
    """The feed's three filters, read off the query string as one value: what the change did,
    the kind of its record, and a fragment of the record's name."""
    with _refusals():
        return ActivityFilter(
            None if kind is None else RecordKind(kind),
            None if action is None else Action(action),
            q,
        )


@contextmanager
def _refusals() -> Iterator[None]:
    """Turns a history refusal into the status the design's table gives it, as the other
    routers' `_refusals` do: the mapping is this router's contract, not the application's."""
    try:
        yield
    except HistoryError as error:
        status_code = _STATUS_BY_ERROR.get(type(error), status.HTTP_422_UNPROCESSABLE_CONTENT)
        raise HTTPException(status_code, str(error)) from error
