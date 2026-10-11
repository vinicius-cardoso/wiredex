from typing import Protocol

from wiredex.preferences.domain.preferences import WorkspacePreferences
from wiredex.shared_kernel.application.ports import UnitOfWork


class Preferences(Protocol):
    async def get(self) -> WorkspacePreferences | None:
        """The workspace's saved choices, or None when it never saved any."""
        ...

    async def add(self, preferences: WorkspacePreferences) -> None: ...


class PreferencesUnitOfWork(UnitOfWork, Protocol):
    @property
    def preferences(self) -> Preferences: ...
