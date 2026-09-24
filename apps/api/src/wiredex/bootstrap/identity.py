from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.settings import Settings
from wiredex.identity.application.create_account import AccountServices, CreateAccount
from wiredex.identity.infrastructure.passwords import Argon2PasswordHasher
from wiredex.identity.infrastructure.unit_of_work import SqlIdentityUnitOfWork
from wiredex.shared_kernel.infrastructure.clock import SystemClock
from wiredex.shared_kernel.infrastructure.ids import Uuid7Generator


@asynccontextmanager
async def create_account_use_case(settings: Settings) -> AsyncIterator[CreateAccount]:
    """CreateAccount wired to Postgres, Argon2id and the system clock (for the CLI)."""
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    services = AccountServices(SystemClock(), Uuid7Generator(), Argon2PasswordHasher())
    try:
        yield CreateAccount(lambda: SqlIdentityUnitOfWork(session_factory), services)
    finally:
        await engine.dispose()
