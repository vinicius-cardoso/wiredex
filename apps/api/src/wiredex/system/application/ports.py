from typing import Protocol


class DatabaseProbe(Protocol):
    """Answers whether the database accepts queries right now."""

    async def is_reachable(self) -> bool: ...
