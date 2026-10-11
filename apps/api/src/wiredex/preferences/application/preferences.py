"""Read and change a workspace's settings."""

from collections.abc import Callable

from wiredex.preferences.application.ports import PreferencesUnitOfWork
from wiredex.preferences.domain.preferences import Choices, WorkspaceId, WorkspacePreferences

type UnitOfWorkFactory = Callable[[WorkspaceId], PreferencesUnitOfWork]


class GetPreferences:
    """The workspace's choices, the defaults for one that never saved any. Writes nothing."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId) -> WorkspacePreferences:
        async with self._unit_of_work(workspace_id) as work:
            saved = await work.preferences.get()
        return saved or WorkspacePreferences.default(workspace_id)


class UpdatePreferences:
    """Replaces the workspace's choices whole; the ones it already has write nothing."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, workspace_id: WorkspaceId, choices: Choices) -> WorkspacePreferences:
        async with self._unit_of_work(workspace_id) as work:
            saved = await work.preferences.get()
            preferences = saved or WorkspacePreferences.default(workspace_id)
            changed = preferences.choose(choices)
            if saved is None:
                await work.preferences.add(preferences)
            if changed or saved is None:
                await work.commit()
            return preferences
