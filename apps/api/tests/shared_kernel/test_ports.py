from datetime import UTC

from sqlalchemy.ext.asyncio import create_async_engine

from wiredex.bootstrap.database import create_session_factory
from wiredex.shared_kernel.application.ports import Clock, IdGenerator, UnitOfWork
from wiredex.shared_kernel.infrastructure.clock import SystemClock
from wiredex.shared_kernel.infrastructure.ids import Uuid7Generator
from wiredex.shared_kernel.infrastructure.unit_of_work import SqlUnitOfWork


def test_adapters_satisfy_their_ports() -> None:
    # mypy checks these assignments structurally: an adapter that drifts from its
    # port fails `make typecheck`, not a use case at runtime.
    session_factory = create_session_factory(create_async_engine("postgresql+asyncpg://u@h/d"))
    clock: Clock = SystemClock()
    ids: IdGenerator = Uuid7Generator()
    uow: UnitOfWork = SqlUnitOfWork(session_factory)

    # Used only through the port types, the way use cases will use them.
    assert clock.now().tzinfo is UTC
    assert ids.new_id().version == 7
    assert callable(uow.commit)


def test_sessions_keep_objects_readable_after_commit() -> None:
    session_factory = create_session_factory(create_async_engine("postgresql+asyncpg://u@h/d"))

    assert session_factory.kw["expire_on_commit"] is False
