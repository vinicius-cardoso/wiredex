"""Wire the preferences module: a workspace's settings over Postgres."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from wiredex.preferences.api.router import PreferencesUseCases
from wiredex.preferences.application.preferences import GetPreferences, UpdatePreferences
from wiredex.preferences.domain.preferences import WorkspaceId
from wiredex.preferences.infrastructure.unit_of_work import SqlPreferencesUnitOfWork

type SessionFactory = async_sessionmaker[AsyncSession]


def preferences_use_cases(session_factory: SessionFactory) -> PreferencesUseCases:
    def unit_of_work(workspace_id: WorkspaceId) -> SqlPreferencesUnitOfWork:
        return SqlPreferencesUnitOfWork(session_factory, workspace_id)

    return PreferencesUseCases(
        get_preferences=GetPreferences(unit_of_work),
        update_preferences=UpdatePreferences(unit_of_work),
    )


class PreferredCodePrefix:
    """Inventory's `CodePrefixOf` over the workspace's preferences, read in their own
    transaction."""

    def __init__(self, get_preferences: GetPreferences) -> None:
        self._get_preferences = get_preferences

    async def __call__(self, workspace_id: UUID) -> str:
        return (await self._get_preferences(WorkspaceId(workspace_id))).code_prefix


def code_prefix_of(session_factory: SessionFactory) -> PreferredCodePrefix:
    """What a workspace's new short codes start with, for the use cases that mint them."""

    def unit_of_work(workspace_id: WorkspaceId) -> SqlPreferencesUnitOfWork:
        return SqlPreferencesUnitOfWork(session_factory, workspace_id)

    return PreferredCodePrefix(GetPreferences(unit_of_work))
