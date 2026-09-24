from datetime import UTC, datetime


class SystemClock:
    """Clock backed by the system time, always timezone-aware UTC."""

    def now(self) -> datetime:
        return datetime.now(UTC)
