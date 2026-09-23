from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class BuildInfo:
    """What is running: the release version and the commit it was built from."""

    version: str
    commit: str
    built_at: datetime | None = None
