import json
from collections.abc import Mapping
from decimal import Decimal

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from wiredex.bootstrap.settings import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    """One engine per process. The pool stays small: production has under 1 GB of RAM."""
    return create_async_engine(
        settings.database_url.get_secret_value(),
        json_serializer=_dump_json,
        json_deserializer=_load_json,
        pool_size=5,
        max_overflow=5,
        pool_pre_ping=True,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    # expire_on_commit=False: objects stay readable after commit, for building responses.
    return async_sessionmaker(engine, expire_on_commit=False)


def _dump_json(value: object) -> str:
    """JSON for a JSON column, writing a Decimal as a bare number.

    JSONB numbers are `numeric`, so an unquoted Decimal keeps every digit and two
    spellings of one magnitude are stored as the same value (ADR 0005). Quoting it would
    be exact too, but a JSON string can't be matched with `@>` against the GIN index.

    The containers are walked here because json's own encoder can't be taught this: it
    turns anything it takes for a number into a C double, and whatever `default()` hands
    back is encoded again, so a Decimal could only come out quoted.
    """
    match value:
        case Decimal():
            return _number(value)
        case Mapping():
            pairs = (f"{json.dumps(str(key))}:{_dump_json(item)}" for key, item in value.items())
            return f"{{{','.join(pairs)}}}"
        case list() | tuple():
            return f"[{','.join(_dump_json(item) for item in value)}]"
        case _:
            return json.dumps(value)


def _number(value: Decimal) -> str:
    # str() keeps the exponent as written: Decimal("1E-7") stays 1E-7, valid JSON.
    if not value.is_finite():
        raise ValueError(f"{value} has no JSON number, and no numeric either")
    return str(value)


def _load_json(text: str) -> object:
    """Read JSON back, with a fractional number as the Decimal it was stored as.

    A whole number comes back as an `int`, which is exact as well, and the attribute
    validators read a number written either way.
    """
    return json.loads(text, parse_float=Decimal)
