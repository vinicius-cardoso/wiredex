"""History over HTTP: the workspace's activity feed and a record's timeline (17-history, HTTP).

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

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from wiredex.history.api.schemas import HistoryPageResponse, TimelineKindName
from wiredex.history.application.history import ListActivity, ListTimeline
from wiredex.history.domain.errors import (
    ChangeNotFoundError,
    HistoryError,
    InvalidHistoryCursorError,
    NotRestorableError,
    RecordNotFoundError,
)
from wiredex.history.domain.history import (
    DEFAULT_PAGE_SIZE,
    MAX_CURSOR_LENGTH,
    MAX_PAGE_SIZE,
    ChangeCursor,
    RecordKind,
)
from wiredex.history.domain.values import WorkspaceId


@dataclass(frozen=True, slots=True)
class HistoryUseCases:
    list_activity: ListActivity
    list_timeline: ListTimeline


type CurrentWorkspaceDependency = Callable[[Request], Awaitable[WorkspaceId]]

# The design's Error Handling: what isn't the workspace's is a 404, so an id says nothing about
# another bench; a change that can't be restored is a 409; a cursor the API didn't give is the
# request's content being unprocessable.
_STATUS_BY_ERROR: Mapping[type[HistoryError], int] = {
    ChangeNotFoundError: status.HTTP_404_NOT_FOUND,
    RecordNotFoundError: status.HTTP_404_NOT_FOUND,
    NotRestorableError: status.HTTP_409_CONFLICT,
    InvalidHistoryCursorError: status.HTTP_422_UNPROCESSABLE_CONTENT,
}

type Limit = Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)]
type Cursor = Annotated[str | None, Query(max_length=MAX_CURSOR_LENGTH)]


def create_router(
    use_cases: HistoryUseCases, current_workspace: CurrentWorkspaceDependency
) -> APIRouter:
    router = APIRouter(prefix="/history", tags=["history"])

    @router.get("")
    async def list_activity(
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
        limit: Limit = DEFAULT_PAGE_SIZE,
        cursor: Cursor = None,
    ) -> HistoryPageResponse:
        """The workspace's changes, newest first, and the cursor reading the next ones; 422
        for a cursor the API didn't give (requirements 2.1 to 2.6)."""
        with _refusals():
            page = await use_cases.list_activity(workspace_id, _cursor(cursor), limit)
        return HistoryPageResponse.from_page(page)

    @router.get("/{kind}/{record_id}")
    async def list_timeline(
        kind: TimelineKindName,
        record_id: UUID,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
        limit: Limit = DEFAULT_PAGE_SIZE,
        cursor: Cursor = None,
    ) -> HistoryPageResponse:
        """A part's, unit's, project's or firmware's changes, those to what it holds included,
        newest first; 404 for a record that isn't live in the workspace (requirement 3)."""
        with _refusals():
            record = (RecordKind(kind), record_id)
            page = await use_cases.list_timeline(workspace_id, record, _cursor(cursor), limit)
        return HistoryPageResponse.from_page(page)

    return router


def _cursor(text: str | None) -> ChangeCursor | None:
    return None if text is None else ChangeCursor.decode(text)


@contextmanager
def _refusals() -> Iterator[None]:
    """Turns a history refusal into the status the design's table gives it, as the other
    routers' `_refusals` do: the mapping is this router's contract, not the application's."""
    try:
        yield
    except HistoryError as error:
        status_code = _STATUS_BY_ERROR.get(type(error), status.HTTP_422_UNPROCESSABLE_CONTENT)
        raise HTTPException(status_code, str(error)) from error
