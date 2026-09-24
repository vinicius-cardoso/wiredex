from datetime import UTC, datetime
from types import TracebackType
from typing import Self
from uuid import UUID, uuid7

import pytest

from wiredex.identity.application.create_account import AccountServices, CreateAccount, NewAccount
from wiredex.identity.domain.errors import EmailAlreadyUsedError
from wiredex.identity.domain.model import Membership, User, Workspace
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

pytestmark = pytest.mark.anyio
NOW = datetime(2026, 9, 24, 12, tzinfo=UTC)


class FixedClock:
    def now(self) -> datetime:
        return NOW


class NewIds:
    def new_id(self) -> UUID:
        return uuid7()


class PlainHasher:
    """Readable stand-in: the real Argon2id adapter has its own tests."""

    def hash(self, password: Password) -> PasswordHash:
        return PasswordHash(f"hashed:{password.value}")

    def verify(self, password: Password, password_hash: PasswordHash) -> bool:
        return password_hash.value == f"hashed:{password.value}"


class InMemoryUsers:
    def __init__(self) -> None:
        self.saved: dict[UserId, User] = {}

    async def add(self, user: User) -> None:
        self.saved[user.id] = user

    async def get(self, user_id: UserId) -> User | None:
        return self.saved.get(user_id)

    async def with_email(self, email: Email) -> User | None:
        return next((user for user in self.saved.values() if user.email == email), None)


class InMemoryWorkspaces:
    def __init__(self) -> None:
        self.saved: dict[WorkspaceId, Workspace] = {}

    async def add(self, workspace: Workspace) -> None:
        self.saved[workspace.id] = workspace

    async def get(self, workspace_id: WorkspaceId) -> Workspace | None:
        return self.saved.get(workspace_id)


class InMemoryMemberships:
    def __init__(self) -> None:
        self.saved: list[Membership] = []

    async def add(self, membership: Membership) -> None:
        self.saved.append(membership)

    async def of_user(self, user_id: UserId) -> list[Membership]:
        return [membership for membership in self.saved if membership.user_id == user_id]


class InMemoryIdentity:
    """A unit of work over shared in-memory stores that keeps only committed changes."""

    def __init__(self) -> None:
        self.users = InMemoryUsers()
        self.workspaces = InMemoryWorkspaces()
        self.memberships = InMemoryMemberships()
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


@pytest.fixture
def identity() -> InMemoryIdentity:
    return InMemoryIdentity()


def create_account(identity: InMemoryIdentity) -> CreateAccount:
    return CreateAccount(lambda: identity, AccountServices(FixedClock(), NewIds(), PlainHasher()))


OWNER = NewAccount(Email("owner@example.com"), Name("Vinícius"), Password("correct horse battery"))


async def test_a_new_account_owns_its_personal_workspace(identity: InMemoryIdentity) -> None:
    created = await create_account(identity)(OWNER)

    user = identity.users.saved[created.user_id]
    workspace = identity.workspaces.saved[created.workspace_id]
    assert (user.email, user.name, user.created_at) == (OWNER.email, OWNER.name, NOW)
    assert user.password_hash == PasswordHash("hashed:correct horse battery")
    assert (workspace.name, workspace.kind) == (OWNER.name, WorkspaceKind.PERSONAL)
    assert [(m.workspace_id, m.role) for m in identity.memberships.saved] == [
        (created.workspace_id, Role.OWNER)
    ]
    assert identity.commits == 1


async def test_an_email_can_only_have_one_account(identity: InMemoryIdentity) -> None:
    await create_account(identity)(OWNER)
    again = NewAccount(
        Email("OWNER@example.com"), Name("Someone"), Password("another long password")
    )

    with pytest.raises(EmailAlreadyUsedError, match="already has an account"):
        await create_account(identity)(again)

    assert len(identity.users.saved) == 1
    assert identity.commits == 1
