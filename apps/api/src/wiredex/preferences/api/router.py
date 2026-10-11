"""A workspace's settings over HTTP (24-minimum-stock).

A factory, as the other routers are: the use cases and the workspace dependency come in as
arguments. Whoever acts in a workspace may change its settings; a guest's are their own demo
bench's.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from wiredex.preferences.api.schemas import PreferencesRequest, PreferencesResponse
from wiredex.preferences.application.preferences import GetPreferences, UpdatePreferences
from wiredex.preferences.domain.preferences import StockBasis, WorkspaceId


@dataclass(frozen=True, slots=True)
class PreferencesUseCases:
    get_preferences: GetPreferences
    update_preferences: UpdatePreferences


type CurrentWorkspaceDependency = Callable[[Request], Awaitable[WorkspaceId]]


def create_router(
    use_cases: PreferencesUseCases, current_workspace: CurrentWorkspaceDependency
) -> APIRouter:
    router = APIRouter(prefix="/preferences", tags=["preferences"])

    @router.get("")
    async def get_preferences(
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> PreferencesResponse:
        """The workspace's settings; the defaults for one that never saved any."""
        return PreferencesResponse.from_preferences(await use_cases.get_preferences(workspace_id))

    @router.put("")
    async def update_preferences(
        body: PreferencesRequest,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> PreferencesResponse:
        """Replaces the settings whole; the ones already saved write nothing."""
        saved = await use_cases.update_preferences(workspace_id, StockBasis(body.stock_basis))
        return PreferencesResponse.from_preferences(saved)

    return router
