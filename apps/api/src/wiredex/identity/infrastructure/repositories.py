from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from wiredex.identity.domain.model import Membership, User, Workspace
from wiredex.identity.domain.session import Session
from wiredex.identity.domain.values import Email, SessionId, SessionTokenHash, UserId, WorkspaceId
from wiredex.identity.infrastructure.orm import sessions, users


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

    async def expired(self, now: datetime) -> list[User]:
        result = await self._session.execute(select(User).where(users.c.expires_at <= now))
        return list(result.scalars())

    async def remove(self, user: User) -> None:
        # The database cascades to memberships and sessions (ON DELETE CASCADE).
        await self._session.delete(user)


class SqlWorkspaces:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, workspace: Workspace) -> None:
        self._session.add(workspace)

    async def get(self, workspace_id: WorkspaceId) -> Workspace | None:
        return await self._session.get(Workspace, workspace_id)

    async def remove(self, workspace: Workspace) -> None:
        await self._session.delete(workspace)


class SqlMemberships:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, membership: Membership) -> None:
        self._session.add(membership)

    async def of_user(self, user_id: UserId) -> list[Membership]:
        result = await self._session.execute(select(Membership).filter_by(user_id=user_id))
        return list(result.scalars())


class SqlSessions:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, session: Session) -> None:
        self._session.add(session)

    async def with_token_hash(self, token_hash: SessionTokenHash) -> Session | None:
        result = await self._session.execute(select(Session).filter_by(token_hash=token_hash))
        return result.scalar_one_or_none()

    async def get(self, session_id: SessionId) -> Session | None:
        return await self._session.get(Session, session_id)

    async def of_user(self, user_id: UserId) -> list[Session]:
        result = await self._session.execute(
            select(Session).filter_by(user_id=user_id).order_by(sessions.c.last_seen_at.desc())
        )
        return list(result.scalars())

    async def remove(self, session: Session) -> None:
        await self._session.delete(session)
