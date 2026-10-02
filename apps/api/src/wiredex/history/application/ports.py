"""What history's use cases need: its own tables, and through bootstrap, the modules that own the
records it is about."""

from types import TracebackType
from typing import Protocol, Self


class HistoryChanges(Protocol):
    """The workspace's changes, as the database recorded them."""

    async def clear(self) -> int:
        """Every change of the workspace deleted, their rows with them; how many went."""
        ...


class HistoryUnitOfWork(Protocol):
    @property
    def changes(self) -> HistoryChanges: ...

    async def commit(self) -> None: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...
