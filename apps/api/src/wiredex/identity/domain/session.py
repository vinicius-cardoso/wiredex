from dataclasses import dataclass
from datetime import datetime, timedelta

from wiredex.identity.domain.values import SessionId, SessionTokenHash, UserId

SLIDING_LIFETIME = timedelta(days=30)
ABSOLUTE_LIFETIME = timedelta(days=90)
# Writing last_seen on every request would cost a write per click on a small host.
LAST_SEEN_RESOLUTION = timedelta(minutes=5)


@dataclass(eq=False)
class Session:
    """A logged-in device. Renewed while used; never lives past ABSOLUTE_LIFETIME."""

    id: SessionId
    user_id: UserId
    token_hash: SessionTokenHash
    device: str
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime

    @classmethod
    def start(
        cls,
        session_id: SessionId,
        user_id: UserId,
        token_hash: SessionTokenHash,
        device: str,
        now: datetime,
    ) -> Session:
        return cls(session_id, user_id, token_hash, device[:120], now, now, now + SLIDING_LIFETIME)

    def is_valid(self, now: datetime) -> bool:
        return now < self.expires_at

    def touch(self, now: datetime) -> bool:
        """Extend the session after use. Returns whether anything changed worth saving."""
        if now - self.last_seen_at < LAST_SEEN_RESOLUTION:
            return False
        self.last_seen_at = now
        self.expires_at = min(now + SLIDING_LIFETIME, self.created_at + ABSOLUTE_LIFETIME)
        return True
