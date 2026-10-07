"""Sharing a demo from the app: an owner invites a guest to a bench of their own (ADR 0007)."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

from wiredex.identity.application.create_account import (
    CreatedAccount,
    GuestInvitation,
    NewAccount,
)
from wiredex.identity.application.sessions import CurrentUser
from wiredex.identity.domain.errors import GuestsCannotInviteError
from wiredex.identity.domain.values import Email, GuestLifetime, Name, Password

# Invites the guest and fills their bench with the sample data. The composition root builds
# it, since the samples belong to every other module (ADR 0001).
type InviteWithBench = Callable[[GuestInvitation], Awaitable[CreatedAccount]]


@dataclass(frozen=True, slots=True)
class SharedDemo:
    """What the inviter passes on. The password exists here only: its hash is what is kept."""

    email: Email
    name: Name
    password: Password
    expires_at: datetime


class ShareDemo:
    """An account that doesn't expire invites a guest, for as long as it says.

    The guest gets a demo workspace of their own, with the sample data and none of the
    inviter's: nothing here names the inviter's workspace, and row-level security keeps each
    session to its own (ADR 0007). The password is made here, never chosen by the inviter, so
    the one a guest receives was never anybody else's. A guest can't invite: an invitation
    would outlive the account that made it.
    """

    def __init__(self, invite: InviteWithBench, new_password: Callable[[], str]) -> None:
        self._invite = invite
        self._new_password = new_password

    async def __call__(
        self, inviter: CurrentUser, email: Email, name: Name, lifetime: GuestLifetime
    ) -> SharedDemo:
        if inviter.user.expires_at is not None:
            raise GuestsCannotInviteError
        password = Password(self._new_password())
        invitation = GuestInvitation(NewAccount(email, name, password), lifetime)
        invited = await self._invite(invitation)
        if invited.expires_at is None:  # an invitation always sets one; kept for the type checker
            raise GuestsCannotInviteError
        return SharedDemo(email, name, password, invited.expires_at)
