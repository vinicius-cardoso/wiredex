from collections.abc import Iterable
from datetime import datetime
from typing import Protocol

from wiredex.identity.domain.model import Membership, User, Workspace
from wiredex.identity.domain.session import Session
from wiredex.identity.domain.values import (
    Email,
    Password,
    PasswordHash,
    SessionToken,
    SessionTokenHash,
    UserId,
    WorkspaceId,
)
from wiredex.shared_kernel.application.ports import UnitOfWork


class Users(Protocol):
    async def add(self, user: User) -> None: ...

    async def get(self, user_id: UserId) -> User | None: ...

    async def with_email(self, email: Email) -> User | None: ...


class Workspaces(Protocol):
    async def add(self, workspace: Workspace) -> None: ...

    async def get(self, workspace_id: WorkspaceId) -> Workspace | None: ...


class Memberships(Protocol):
    async def add(self, membership: Membership) -> None: ...

    async def of_user(self, user_id: UserId) -> list[Membership]: ...


class Sessions(Protocol):
    async def add(self, session: Session) -> None: ...

    async def with_token_hash(self, token_hash: SessionTokenHash) -> Session | None: ...

    async def remove(self, session: Session) -> None: ...


class PasswordHasher(Protocol):
    def hash(self, password: Password) -> PasswordHash: ...

    def verify(self, password: Password, password_hash: PasswordHash | None) -> bool:
        """False for a wrong password. With no hash (unknown user), take as long as a
        real check and return False, so response time can't reveal which emails exist."""
        ...


class SessionTokens(Protocol):
    def issue(self) -> SessionToken: ...

    def hash(self, token: SessionToken) -> SessionTokenHash: ...


class LoginThrottle(Protocol):
    """Counts failed logins per key (an account, an IP) inside a time window."""

    def is_blocked(self, keys: Iterable[str], now: datetime) -> bool: ...

    def record_failure(self, keys: Iterable[str], now: datetime) -> None: ...

    def clear(self, key: str) -> None: ...


class IdentityUnitOfWork(UnitOfWork, Protocol):
    # Read-only properties, not attributes: a protocol attribute would have to match
    # exactly, so SqlUsers wouldn't count as Users.
    @property
    def users(self) -> Users: ...

    @property
    def workspaces(self) -> Workspaces: ...

    @property
    def memberships(self) -> Memberships: ...

    @property
    def sessions(self) -> Sessions: ...
