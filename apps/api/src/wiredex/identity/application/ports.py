from typing import Protocol

from wiredex.identity.domain.model import Membership, User, Workspace
from wiredex.identity.domain.values import Email, Password, PasswordHash, UserId, WorkspaceId
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


class PasswordHasher(Protocol):
    def hash(self, password: Password) -> PasswordHash: ...

    def verify(self, password: Password, password_hash: PasswordHash) -> bool: ...


class IdentityUnitOfWork(UnitOfWork, Protocol):
    # Read-only properties, not attributes: a protocol attribute would have to match
    # exactly, so SqlUsers wouldn't count as Users.
    @property
    def users(self) -> Users: ...

    @property
    def workspaces(self) -> Workspaces: ...

    @property
    def memberships(self) -> Memberships: ...
