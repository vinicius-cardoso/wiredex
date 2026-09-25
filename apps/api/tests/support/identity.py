"""In-memory stand-ins for the identity ports, shared by the use-case tests."""

import hashlib
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Self
from uuid import UUID, uuid7

from wiredex.identity.api.router import SessionUseCases
from wiredex.identity.application.create_account import AccountServices, CreateAccount, NewAccount
from wiredex.identity.application.sessions import (
    Authenticate,
    ListSessions,
    LogIn,
    LoginServices,
    LogOut,
    RevokeSession,
)
from wiredex.identity.domain.model import Membership, User, Workspace
from wiredex.identity.domain.session import Session
from wiredex.identity.domain.values import (
    Email,
    Name,
    Password,
    PasswordHash,
    SessionId,
    SessionToken,
    SessionTokenHash,
    UserId,
    WorkspaceId,
    WorkspaceKind,
)
from wiredex.identity.infrastructure.throttle import InMemoryLoginThrottle

NOW = datetime(2026, 9, 24, 12, tzinfo=UTC)
EMAIL, PASSWORD = Email("owner@example.com"), Password("correct horse battery")


class ManualClock:
    """A clock that only moves when told to."""

    def __init__(self, now: datetime = NOW) -> None:
        self.current = now

    def now(self) -> datetime:
        return self.current

    def advance(self, delta: timedelta) -> None:
        self.current += delta


class NewIds:
    def new_id(self) -> UUID:
        return uuid7()


class PlainHasher:
    """Readable stand-in: the real Argon2id adapter has its own tests."""

    def hash(self, password: Password) -> PasswordHash:
        return PasswordHash(f"hashed:{password.value}")

    def verify(self, password: Password, password_hash: PasswordHash | None) -> bool:
        return password_hash is not None and password_hash.value == f"hashed:{password.value}"


class CountingTokens:
    """Predictable tokens: token-1, token-2, ..."""

    def __init__(self) -> None:
        self.issued = 0

    def issue(self) -> SessionToken:
        self.issued += 1
        return SessionToken(f"token-{self.issued}")

    def hash(self, token: SessionToken) -> SessionTokenHash:
        return SessionTokenHash(hashlib.sha256(token.value.encode()).hexdigest())


class InMemoryUsers:
    def __init__(self) -> None:
        self.saved: dict[UserId, User] = {}

    async def add(self, user: User) -> None:
        self.saved[user.id] = user

    async def get(self, user_id: UserId) -> User | None:
        return self.saved.get(user_id)

    async def with_email(self, email: Email) -> User | None:
        return next((user for user in self.saved.values() if user.email == email), None)

    async def expired(self, now: datetime) -> list[User]:
        return [u for u in self.saved.values() if u.expires_at is not None and u.expires_at <= now]

    async def remove(self, user: User) -> None:
        del self.saved[user.id]


class InMemoryWorkspaces:
    def __init__(self) -> None:
        self.saved: dict[WorkspaceId, Workspace] = {}

    async def add(self, workspace: Workspace) -> None:
        self.saved[workspace.id] = workspace

    async def remove(self, workspace: Workspace) -> None:
        del self.saved[workspace.id]

    async def get(self, workspace_id: WorkspaceId) -> Workspace | None:
        return self.saved.get(workspace_id)

    async def of_kind(self, kind: WorkspaceKind) -> list[Workspace]:
        return [workspace for workspace in self.saved.values() if workspace.kind is kind]

    async def all(self) -> list[Workspace]:
        return list(self.saved.values())


class InMemoryMemberships:
    def __init__(self) -> None:
        self.saved: list[Membership] = []

    async def add(self, membership: Membership) -> None:
        self.saved.append(membership)

    async def of_user(self, user_id: UserId) -> list[Membership]:
        return [membership for membership in self.saved if membership.user_id == user_id]


class InMemorySessions:
    def __init__(self) -> None:
        self.saved: dict[SessionTokenHash, Session] = {}

    async def add(self, session: Session) -> None:
        self.saved[session.token_hash] = session

    async def with_token_hash(self, token_hash: SessionTokenHash) -> Session | None:
        return self.saved.get(token_hash)

    async def get(self, session_id: SessionId) -> Session | None:
        return next((s for s in self.saved.values() if s.id == session_id), None)

    async def of_user(self, user_id: UserId) -> list[Session]:
        mine = [s for s in self.saved.values() if s.user_id == user_id]
        return sorted(mine, key=lambda s: s.last_seen_at, reverse=True)

    async def remove(self, session: Session) -> None:
        self.saved.pop(session.token_hash, None)


class InMemoryIdentity:
    """A unit of work over shared in-memory stores; counts commits."""

    def __init__(self) -> None:
        self.users = InMemoryUsers()
        self.workspaces = InMemoryWorkspaces()
        self.memberships = InMemoryMemberships()
        self.sessions = InMemorySessions()
        self.commits = 0

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1


class World:
    """The identity use cases over in-memory fakes, with one owner account available."""

    def __init__(self) -> None:
        self.identity = InMemoryIdentity()
        self.clock = ManualClock()
        self.tokens = CountingTokens()
        self.throttle = InMemoryLoginThrottle()
        services = LoginServices(self.clock, NewIds(), PlainHasher(), self.tokens, self.throttle)
        self.log_in = LogIn(lambda: self.identity, services)
        self.authenticate = Authenticate(lambda: self.identity, self.clock, self.tokens)
        self.log_out = LogOut(lambda: self.identity, self.tokens)
        self.list_sessions = ListSessions(lambda: self.identity, self.clock)
        self.revoke_session = RevokeSession(lambda: self.identity)

    async def with_owner(self) -> World:
        create = CreateAccount(
            lambda: self.identity, AccountServices(self.clock, NewIds(), PlainHasher())
        )
        await create(NewAccount(EMAIL, Name("Owner"), PASSWORD))
        return self

    def session_use_cases(self) -> SessionUseCases:
        return SessionUseCases(
            self.log_in,
            self.authenticate,
            self.log_out,
            self.list_sessions,
            self.revoke_session,
        )
