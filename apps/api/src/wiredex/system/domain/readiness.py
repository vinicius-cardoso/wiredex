from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Readiness:
    """Whether the API can serve requests that need its dependencies."""

    database_reachable: bool

    @property
    def is_ready(self) -> bool:
        return self.database_reachable
