from typing import Self

from wiredex.identity.infrastructure.repositories import (
    SqlMemberships,
    SqlSessions,
    SqlUsers,
    SqlWorkspaces,
)
from wiredex.shared_kernel.infrastructure.unit_of_work import SqlUnitOfWork


class SqlIdentityUnitOfWork(SqlUnitOfWork):
    """One transaction with the identity repositories bound to its session."""

    users: SqlUsers
    workspaces: SqlWorkspaces
    memberships: SqlMemberships
    sessions: SqlSessions

    async def __aenter__(self) -> Self:
        await super().__aenter__()
        self.users = SqlUsers(self.session)
        self.workspaces = SqlWorkspaces(self.session)
        self.memberships = SqlMemberships(self.session)
        self.sessions = SqlSessions(self.session)
        return self
