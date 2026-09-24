from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.settings import Settings
from wiredex.identity.api.router import SessionUseCases
from wiredex.identity.application.create_account import (
    AccountServices,
    CreateAccount,
    InviteGuest,
)
from wiredex.identity.application.guests import RemoveExpiredGuests
from wiredex.identity.application.sessions import (
    Authenticate,
    ListSessions,
    LogIn,
    LoginServices,
    LogOut,
    RevokeSession,
)
from wiredex.identity.infrastructure.passwords import Argon2PasswordHasher
from wiredex.identity.infrastructure.throttle import InMemoryLoginThrottle
from wiredex.identity.infrastructure.tokens import SecretSessionTokens
from wiredex.identity.infrastructure.unit_of_work import SqlIdentityUnitOfWork
from wiredex.shared_kernel.infrastructure.clock import SystemClock
from wiredex.shared_kernel.infrastructure.ids import Uuid7Generator

type IdentityUnitOfWorkFactory = Callable[[], SqlIdentityUnitOfWork]


@asynccontextmanager
async def _sql_identity(settings: Settings) -> AsyncIterator[IdentityUnitOfWorkFactory]:
    """Identity units of work over Postgres, for one CLI command."""
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    try:
        yield lambda: SqlIdentityUnitOfWork(session_factory)
    finally:
        await engine.dispose()


def _account_services() -> AccountServices:
    return AccountServices(SystemClock(), Uuid7Generator(), Argon2PasswordHasher())


@asynccontextmanager
async def create_account_use_case(settings: Settings) -> AsyncIterator[CreateAccount]:
    """CreateAccount wired to Postgres, Argon2id and the system clock (for the CLI)."""
    async with _sql_identity(settings) as unit_of_work:
        yield CreateAccount(unit_of_work, _account_services())


@asynccontextmanager
async def invite_guest_use_case(settings: Settings) -> AsyncIterator[InviteGuest]:
    async with _sql_identity(settings) as unit_of_work:
        yield InviteGuest(unit_of_work, _account_services())


@asynccontextmanager
async def remove_expired_guests_use_case(
    settings: Settings,
) -> AsyncIterator[RemoveExpiredGuests]:
    async with _sql_identity(settings) as unit_of_work:
        yield RemoveExpiredGuests(unit_of_work, SystemClock())


def session_use_cases(session_factory: async_sessionmaker[AsyncSession]) -> SessionUseCases:
    """The session use cases, wired to Postgres (for the web app)."""

    def unit_of_work() -> SqlIdentityUnitOfWork:
        return SqlIdentityUnitOfWork(session_factory)

    clock, tokens = SystemClock(), SecretSessionTokens()
    services = LoginServices(
        clock, Uuid7Generator(), Argon2PasswordHasher(), tokens, InMemoryLoginThrottle()
    )
    return SessionUseCases(
        log_in=LogIn(unit_of_work, services),
        authenticate=Authenticate(unit_of_work, clock, tokens),
        log_out=LogOut(unit_of_work, tokens),
        list_sessions=ListSessions(unit_of_work, clock),
        revoke_session=RevokeSession(unit_of_work),
    )
