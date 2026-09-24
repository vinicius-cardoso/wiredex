from collections.abc import Callable
from dataclasses import dataclass

from wiredex.identity.application.ports import IdentityUnitOfWork, PasswordHasher
from wiredex.identity.domain.errors import EmailAlreadyUsedError
from wiredex.identity.domain.model import Membership, User, Workspace
from wiredex.identity.domain.values import (
    Email,
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
class CreatedAccount:
    user_id: UserId
    workspace_id: WorkspaceId


@dataclass(frozen=True, slots=True)
class AccountServices:
    clock: Clock
    ids: IdGenerator
    hasher: PasswordHasher


class CreateAccount:
    """A user, their personal workspace and an owner membership, in one transaction."""

    def __init__(
        self, unit_of_work: Callable[[], IdentityUnitOfWork], services: AccountServices
    ) -> None:
        self._unit_of_work = unit_of_work
        self._services = services

    async def __call__(self, account: NewAccount) -> CreatedAccount:
        now = self._services.clock.now()
        user = User(
            id=UserId(self._services.ids.new_id()),
            email=account.email,
            name=account.name,
            password_hash=self._services.hasher.hash(account.password),
            created_at=now,
        )
        bench = Workspace(
            WorkspaceId(self._services.ids.new_id()), account.name, WorkspaceKind.PERSONAL, now
        )
        async with self._unit_of_work() as work:
            if await work.users.with_email(account.email) is not None:
                raise EmailAlreadyUsedError(f"{account.email} already has an account")
            await work.users.add(user)
            await work.workspaces.add(bench)
            await work.memberships.add(Membership(user.id, bench.id, Role.OWNER, now))
            await work.commit()
        return CreatedAccount(user.id, bench.id)
