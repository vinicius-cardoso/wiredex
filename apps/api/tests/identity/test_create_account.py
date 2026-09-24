import pytest

from support.identity import NOW, InMemoryIdentity, ManualClock, NewIds, PlainHasher
from wiredex.identity.application.create_account import AccountServices, CreateAccount, NewAccount
from wiredex.identity.domain.errors import EmailAlreadyUsedError
from wiredex.identity.domain.values import (
    Email,
    Name,
    Password,
    PasswordHash,
    Role,
    WorkspaceKind,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def identity() -> InMemoryIdentity:
    return InMemoryIdentity()


def create_account(identity: InMemoryIdentity) -> CreateAccount:
    return CreateAccount(lambda: identity, AccountServices(ManualClock(), NewIds(), PlainHasher()))


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
