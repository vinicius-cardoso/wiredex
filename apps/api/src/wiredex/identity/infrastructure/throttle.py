from collections import defaultdict, deque
from collections.abc import Iterable
from datetime import datetime, timedelta

WINDOW = timedelta(minutes=15)
# Failures allowed per key inside WINDOW, by key prefix ("account:...", "ip:...").
LIMITS = {"account": 5, "ip": 20}


class InMemoryLoginThrottle:
    """Failed logins per account and per IP in the last 15 minutes.

    In memory is enough while the API runs as one process (ADR 0009); a restart resets
    the counters, which only ever helps a locked-out owner.
    """

    def __init__(self) -> None:
        self._failures: defaultdict[str, deque[datetime]] = defaultdict(deque)

    def is_blocked(self, keys: Iterable[str], now: datetime) -> bool:
        return any(len(self._recent(key, now)) >= _limit(key) for key in keys)

    def record_failure(self, keys: Iterable[str], now: datetime) -> None:
        for key in keys:
            self._recent(key, now).append(now)

    def clear(self, key: str) -> None:
        self._failures.pop(key, None)

    def _recent(self, key: str, now: datetime) -> deque[datetime]:
        failures = self._failures[key]
        while failures and now - failures[0] >= WINDOW:
            failures.popleft()
        return failures


def _limit(key: str) -> int:
    return LIMITS[key.split(":", 1)[0]]
