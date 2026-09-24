from datetime import timedelta

import pytest

from support.identity import NOW, InMemoryIdentity, ManualClock, NewIds, PlainHasher
from wiredex.identity.application.create_account import (
    AccountServices,
    CreateAccount,
    GuestInvitation,
    InviteGuest,
    NewAccount,
)
from wiredex.identity.domain.errors import EmailAlreadyUsedError
from wiredex.identity.domain.values import (
    Email,
    GuestLifetime,
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


def invite_guest(identity: InMemoryIdentity) -> InviteGuest:
    return InviteGuest(lambda: identity, AccountServices(ManualClock(), NewIds(), PlainHasher()))


GUEST = NewAccount(Email("friend@example.com"), Name("Friend"), Password("generated password"))


async def test_a_guest_gets_an_expiring_account_in_a_demo_workspace_of_their_own(
    identity: InMemoryIdentity,
) -> None:
    invited = await invite_guest(identity)(GuestInvitation(GUEST, GuestLifetime.parse("7d")))

    user = identity.users.saved[invited.user_id]
    workspace = identity.workspaces.saved[invited.workspace_id]
    assert user.expires_at == invited.expires_at == NOW + timedelta(days=7)
    assert (workspace.name, workspace.kind) == (Name("Demo bench"), WorkspaceKind.DEMO)
    assert [(m.workspace_id, m.role) for m in identity.memberships.saved] == [
        (invited.workspace_id, Role.GUEST)
    ]


async def test_two_guests_never_share_a_demo_workspace(identity: InMemoryIdentity) -> None:
    lifetime = GuestLifetime.parse("1d")
    other = NewAccount(Email("other@example.com"), Name("Other"), Password("generated password"))

    first = await invite_guest(identity)(GuestInvitation(GUEST, lifetime))
    second = await invite_guest(identity)(GuestInvitation(other, lifetime))

    assert first.workspace_id != second.workspace_id


async def test_a_guest_cannot_take_an_email_that_has_an_account(
    identity: InMemoryIdentity,
) -> None:
    await create_account(identity)(OWNER)
    taken = NewAccount(OWNER.email, Name("Guest"), Password("generated password"))

    with pytest.raises(EmailAlreadyUsedError):
        await invite_guest(identity)(GuestInvitation(taken, GuestLifetime.parse("7d")))
