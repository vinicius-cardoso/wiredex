from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from wiredex.identity.domain.model import Membership, User, Workspace
from wiredex.identity.domain.values import Email, UserId, WorkspaceId


class SqlUsers:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, user: User) -> None:
        self._session.add(user)

    async def get(self, user_id: UserId) -> User | None:
        return await self._session.get(User, user_id)

    async def with_email(self, email: Email) -> User | None:
        result = await self._session.execute(select(User).filter_by(email=email))
        return result.scalar_one_or_none()


class SqlWorkspaces:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, workspace: Workspace) -> None:
        self._session.add(workspace)

    async def get(self, workspace_id: WorkspaceId) -> Workspace | None:
        return await self._session.get(Workspace, workspace_id)


class SqlMemberships:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, membership: Membership) -> None:
        self._session.add(membership)

    async def of_user(self, user_id: UserId) -> list[Membership]:
        result = await self._session.execute(select(Membership).filter_by(user_id=user_id))
        return list(result.scalars())
