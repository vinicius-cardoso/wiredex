from dataclasses import dataclass, field
from datetime import datetime

from wiredex.identity.domain.errors import PasswordLikeAccountError
from wiredex.identity.domain.values import (
    Email,
    Name,
    Password,
    PasswordHash,
    Role,
    UserId,
    WorkspaceId,
    WorkspaceKind,
)

MIN_GUESSABLE_LENGTH = 4


@dataclass(eq=False)
class User:
    """Someone who can log in. Guests get an expiry date; the owner doesn't."""

    id: UserId
    email: Email
    name: Name
    password_hash: PasswordHash
    created_at: datetime
    expires_at: datetime | None = None

    def is_active(self, now: datetime) -> bool:
        return self.expires_at is None or now < self.expires_at

    def ensure_unlike_account(self, password: Password) -> None:
        """Refuses a password that is, or holds, the email, its part before the @, or the
        name: what a guess starts with. Case is ignored, and a part shorter than four
        characters is too common inside other words to count."""
        typed = password.value.casefold()
        email = self.email.value.casefold()
        guessable = (email, email.split("@", 1)[0], self.name.value.casefold())
        if any(len(part) >= MIN_GUESSABLE_LENGTH and part in typed for part in guessable):
            raise PasswordLikeAccountError

    def change_password(self, password_hash: PasswordHash) -> None:
        self.password_hash = password_hash


@dataclass(eq=False)
class Workspace:
    """A separate set of data: your real bench, or a guest's demo bench (ADR 0007)."""

    id: WorkspaceId
    name: Name
    kind: WorkspaceKind
    created_at: datetime


@dataclass(eq=False)
class Membership:
    """Grants a user a role in one workspace."""

    user_id: UserId
    workspace_id: WorkspaceId
    role: Role
    created_at: datetime = field(compare=False)

    def can_manage_workspace(self) -> bool:
        return self.role is Role.OWNER
