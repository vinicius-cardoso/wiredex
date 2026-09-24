from typing import Self

from wiredex.identity.infrastructure.repositories import SqlMemberships, SqlUsers, SqlWorkspaces
from wiredex.shared_kernel.infrastructure.unit_of_work import SqlUnitOfWork


class SqlIdentityUnitOfWork(SqlUnitOfWork):
    """One transaction with the identity repositories bound to its session."""

    users: SqlUsers
    workspaces: SqlWorkspaces
    memberships: SqlMemberships

    async def __aenter__(self) -> Self:
        await super().__aenter__()
        self.users = SqlUsers(self.session)
        self.workspaces = SqlWorkspaces(self.session)
        self.memberships = SqlMemberships(self.session)
        return self
