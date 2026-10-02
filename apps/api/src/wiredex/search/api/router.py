"""The search over HTTP: the workspace's parts, units, projects, firmware, categories and
locations matching a text, in one read (19-command-palette, HTTP).

A factory, as the other routers are: the use case and the workspace dependency come in as
arguments, so the composition root decides what runs. The search never imports identity or the
modules whose records it finds: `bootstrap/app.py` builds `current_workspace` from the session
use cases, and `bootstrap/search.py` builds a source per kind over each module's use cases. A
read only, so no CSRF.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from wiredex.search.api.schemas import SearchResultsResponse
from wiredex.search.application.search import SearchWorkspace
from wiredex.search.domain.errors import SearchError
from wiredex.search.domain.search import DEFAULT_LIMIT, MAX_LIMIT, MAX_TEXT_LENGTH, SearchText
from wiredex.search.domain.values import WorkspaceId


@dataclass(frozen=True, slots=True)
class SearchUseCases:
    search_workspace: SearchWorkspace


type CurrentWorkspaceDependency = Callable[[Request], Awaitable[WorkspaceId]]


def create_router(
    use_cases: SearchUseCases, current_workspace: CurrentWorkspaceDependency
) -> APIRouter:
    router = APIRouter(prefix="/search", tags=["search"])

    @router.get("")
    async def search_workspace(
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
        q: Annotated[str, Query(max_length=MAX_TEXT_LENGTH)],
        limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    ) -> SearchResultsResponse:
        """The records whose identifying text holds `q`, case aside, a group per kind that found
        something, each with the titles starting with it first and whether more match; 422 for
        a text blank once trimmed (requirements 1.1 to 1.5, 2.1, 2.2)."""
        try:
            text = SearchText.of(q)
        except SearchError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
        found = await use_cases.search_workspace(workspace_id, text, limit)
        return SearchResultsResponse.from_results(found)

    return router
