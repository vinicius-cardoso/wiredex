from dataclasses import dataclass, field
from datetime import datetime

from wiredex.identity.domain.values import (
    Email,
    Name,
    PasswordHash,
    Role,
    UserId,
    WorkspaceId,
    WorkspaceKind,
)


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
