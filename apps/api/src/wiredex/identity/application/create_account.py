from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from wiredex.identity.application.ports import IdentityUnitOfWork, PasswordHasher
from wiredex.identity.domain.errors import EmailAlreadyUsedError
from wiredex.identity.domain.model import Membership, User, Workspace
from wiredex.identity.domain.values import (
    Email,
    GuestLifetime,
    Name,
    Password,
    Role,
    UserId,
    WorkspaceId,
    WorkspaceKind,
)
from wiredex.shared_kernel.application.ports import Clock, IdGenerator


@dataclass(frozen=True, slots=True)
class NewAccount:
    email: Email
    name: Name
    password: Password


@dataclass(frozen=True, slots=True)
class GuestInvitation:
    account: NewAccount
    lifetime: GuestLifetime


@dataclass(frozen=True, slots=True)
class CreatedAccount:
    user_id: UserId
    workspace_id: WorkspaceId
    expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class AccountServices:
    clock: Clock
    ids: IdGenerator
    hasher: PasswordHasher


type UnitOfWorkFactory = Callable[[], IdentityUnitOfWork]

DEMO_WORKSPACE_NAME = Name("Demo bench")


class CreateAccount:
    """A user, their personal workspace and an owner membership, in one transaction."""

    def __init__(self, unit_of_work: UnitOfWorkFactory, services: AccountServices) -> None:
        self._unit_of_work = unit_of_work
        self._services = services

    async def __call__(self, account: NewAccount) -> CreatedAccount:
        opening = _Opening(self._services, account)
        bench = opening.workspace(account.name, WorkspaceKind.PERSONAL)
        return await opening.save(self._unit_of_work, bench, Role.OWNER)


class InviteGuest:
    """A guest account that expires, as the only member of its own demo workspace.

    A guest can do anything in their demo bench and nothing anywhere else (ADR 0007).
    Each guest gets a bench of their own, so guests never see each other's changes.
    """

    def __init__(self, unit_of_work: UnitOfWorkFactory, services: AccountServices) -> None:
        self._unit_of_work = unit_of_work
        self._services = services

    async def __call__(self, invitation: GuestInvitation) -> CreatedAccount:
        opening = _Opening(self._services, invitation.account)
        opening.user.expires_at = opening.now + invitation.lifetime.value
        bench = opening.workspace(DEMO_WORKSPACE_NAME, WorkspaceKind.DEMO)
        return await opening.save(self._unit_of_work, bench, Role.GUEST)


class _Opening:
    """The parts of a new account, saved together or not at all."""

    def __init__(self, services: AccountServices, account: NewAccount) -> None:
        self._ids = services.ids
        self.now = services.clock.now()
        self.user = User(
            id=UserId(self._ids.new_id()),
            email=account.email,
            name=account.name,
            password_hash=services.hasher.hash(account.password),
            created_at=self.now,
        )

    def workspace(self, name: Name, kind: WorkspaceKind) -> Workspace:
        return Workspace(WorkspaceId(self._ids.new_id()), name, kind, self.now)

    async def save(
        self, unit_of_work: UnitOfWorkFactory, workspace: Workspace, role: Role
    ) -> CreatedAccount:
        async with unit_of_work() as work:
            if await work.users.with_email(self.user.email) is not None:
                raise EmailAlreadyUsedError(f"{self.user.email} already has an account")
            await work.users.add(self.user)
            await work.workspaces.add(workspace)
            await work.memberships.add(Membership(self.user.id, workspace.id, role, self.now))
            await work.commit()
        return CreatedAccount(self.user.id, workspace.id, self.user.expires_at)
