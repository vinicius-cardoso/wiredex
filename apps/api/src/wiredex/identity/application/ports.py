from typing import Protocol

from wiredex.identity.domain.model import Membership, User, Workspace
from wiredex.identity.domain.values import Email, UserId, WorkspaceId
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


class IdentityUnitOfWork(UnitOfWork, Protocol):
    users: Users
    workspaces: Workspaces
    memberships: Memberships
