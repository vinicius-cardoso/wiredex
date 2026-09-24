from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid7

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from wiredex.bootstrap.database import create_session_factory
from wiredex.identity.domain.model import Membership, User, Workspace
from wiredex.identity.domain.session import Session
from wiredex.identity.domain.values import (
    Email,
    Name,
    PasswordHash,
    Role,
    SessionId,
    SessionTokenHash,
    UserId,
    WorkspaceId,
    WorkspaceKind,
)
from wiredex.identity.infrastructure.unit_of_work import SqlIdentityUnitOfWork

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

NOW = datetime(2026, 9, 24, 12, tzinfo=UTC)


@pytest.fixture
async def engine(migrated_database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(migrated_database_url)
    yield engine
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE users, workspaces, memberships, sessions CASCADE"))
    await engine.dispose()


def uow(engine: AsyncEngine) -> SqlIdentityUnitOfWork:
    return SqlIdentityUnitOfWork(create_session_factory(engine))


def a_user(email: str) -> User:
    return User(UserId(uuid7()), Email(email), Name("Owner"), PasswordHash("hash"), NOW)


async def test_a_user_is_found_by_email_whatever_its_case(engine: AsyncEngine) -> None:
    owner = a_user("owner@example.com")
    async with uow(engine) as work:
        await work.users.add(owner)
        await work.commit()

    async with uow(engine) as work:
        found = await work.users.with_email(Email("OWNER@Example.com"))

    assert found is not None
    assert (found.id, found.email, found.name) == (owner.id, owner.email, owner.name)


async def test_memberships_link_users_to_workspaces(engine: AsyncEngine) -> None:
    owner = a_user("owner@example.com")
    bench = Workspace(WorkspaceId(uuid7()), Name("My bench"), WorkspaceKind.PERSONAL, NOW)
    async with uow(engine) as work:
        await work.users.add(owner)
        await work.workspaces.add(bench)
        await work.memberships.add(Membership(owner.id, bench.id, Role.OWNER, NOW))
        await work.commit()

    async with uow(engine) as work:
        memberships = await work.memberships.of_user(owner.id)
        workspace = await work.workspaces.get(bench.id)

    assert [(m.workspace_id, m.role) for m in memberships] == [(bench.id, Role.OWNER)]
    assert workspace is not None
    assert workspace.kind is WorkspaceKind.PERSONAL


async def save_twice(engine: AsyncEngine) -> None:
    async with uow(engine) as work:
        await work.users.add(a_user("same@example.com"))
        await work.users.add(a_user("SAME@example.com"))
        await work.commit()


async def test_the_database_rejects_a_second_account_with_the_same_email(
    engine: AsyncEngine,
) -> None:
    with pytest.raises(IntegrityError, match="uq_users_email"):
        await save_twice(engine)


def a_session(owner: User, device: str, last_seen: datetime) -> Session:
    session = Session.start(
        SessionId(uuid7()), owner.id, SessionTokenHash(f"hash of {device}"), device, NOW
    )
    session.last_seen_at = last_seen
    return session


async def test_a_users_sessions_come_most_recently_used_first(engine: AsyncEngine) -> None:
    owner, other = a_user("owner@example.com"), a_user("other@example.com")
    laptop = a_session(owner, "Laptop", NOW)
    phone = a_session(owner, "Phone", NOW + timedelta(hours=1))
    async with uow(engine) as work:
        await work.users.add(owner)
        await work.users.add(other)
        for session in (laptop, phone, a_session(other, "Theirs", NOW)):
            await work.sessions.add(session)
        await work.commit()

    async with uow(engine) as work:
        listed = await work.sessions.of_user(owner.id)
        found = await work.sessions.get(laptop.id)

    assert [s.device for s in listed] == ["Phone", "Laptop"]
    assert found is not None
    assert found.device == "Laptop"
