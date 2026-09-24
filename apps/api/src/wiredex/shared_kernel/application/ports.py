from datetime import datetime
from types import TracebackType
from typing import Protocol, Self
from uuid import UUID


class Clock(Protocol):
    """The current time, injected so tests can control it."""

    def now(self) -> datetime: ...


class IdGenerator(Protocol):
    """New entity identifiers."""

    def new_id(self) -> UUID: ...


class UnitOfWork(Protocol):
    """One business transaction. Nothing is saved unless `commit()` is called."""

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...
