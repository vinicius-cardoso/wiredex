"""Wire the preferences module: a workspace's settings over Postgres."""

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
