"""Column types that store inventory value objects as plain columns and read them back.

The same pattern catalog and identity use for their own values. The three aren't shared
because modules don't import each other (ADR 0001); promote a type to the shared kernel when
a third module needs the same value, as `WorkspaceId` itself will be.
"""

from collections.abc import Callable
from typing import Any, Protocol, override

from sqlalchemy import Dialect, Integer, String, TypeDecorator
from sqlalchemy.sql.operators import OperatorType
from sqlalchemy.types import TypeEngine

from wiredex.inventory.domain.unit import UnitStatus
from wiredex.inventory.domain.values import (
    MAX_LOCATION_NAME_LENGTH,
    MAX_NOTE_LENGTH,
    MAX_SERIAL_LENGTH,
    LocationName,
    Mac,
    Note,
    Quantity,
    Serial,
    ShortCode,
)

# The short code is `WX-` plus a letter plus at least four digits; four is the display
# minimum and a workspace past 9999 widens the number, so the column has slack.
MAX_SHORT_CODE_LENGTH = 16

# Canonical `aa:bb:cc:dd:ee:ff`: six two-hex octets, five colons — seventeen characters.
MAX_MAC_LENGTH = 17


class _HasStrValue(Protocol):
    @property
    def value(self) -> str: ...


class _StrValueObjectType[V: _HasStrValue](TypeDecorator[V]):
    """A value object with a single `value: str`, stored as that string."""

    impl = String(255)  # each subclass sets its own length
    cache_ok = True
    rebuild: Callable[[str], V]

    @override
    def coerce_compared_value(self, op: OperatorType | None, value: Any) -> TypeEngine[Any]:
        # Plain text on the other side of a comparison stays plain text. A TypeDecorator
        # assumes its own type there, which would send a LIKE pattern or a folded string
        # through process_bind_param and ask a str for its `.value`.
        if isinstance(value, str):
            return self.impl_instance
        return self

    @override
    def process_bind_param(self, value: V | None, dialect: Dialect) -> str | None:
        return None if value is None else value.value

    @override
    def process_result_value(self, value: str | None, dialect: Dialect) -> V | None:
        return None if value is None else type(self).rebuild(value)


class LocationNameType(_StrValueObjectType[LocationName]):
    impl = String(MAX_LOCATION_NAME_LENGTH)
    rebuild = LocationName
    cache_ok = True  # SQLAlchemy checks each class itself, not the base


class ShortCodeType(_StrValueObjectType[ShortCode]):
    impl = String(MAX_SHORT_CODE_LENGTH)
    rebuild = ShortCode
    cache_ok = True  # SQLAlchemy checks each class itself, not the base


class NoteType(_StrValueObjectType[Note]):
    impl = String(MAX_NOTE_LENGTH)
    rebuild = Note
    cache_ok = True  # SQLAlchemy checks each class itself, not the base


class SerialType(_StrValueObjectType[Serial]):
    impl = String(MAX_SERIAL_LENGTH)
    rebuild = Serial
    cache_ok = True  # SQLAlchemy checks each class itself, not the base


class MacType(_StrValueObjectType[Mac]):
    impl = String(MAX_MAC_LENGTH)
    rebuild = Mac
    cache_ok = True  # SQLAlchemy checks each class itself, not the base


class UnitStatusType(TypeDecorator[UnitStatus]):
    """A unit's status, stored as its string value. Text with a CHECK on the column, never a
    Postgres enum type, so a v0.5.0 status is a migration and not an ALTER TYPE (the pattern
    the movement kind and reason follow)."""

    impl = String(16)
    cache_ok = True  # SQLAlchemy checks each class itself, not the base

    @override
    def process_bind_param(self, value: UnitStatus | None, dialect: Dialect) -> str | None:
        return None if value is None else value.value

    @override
    def process_result_value(self, value: str | None, dialect: Dialect) -> UnitStatus | None:
        return None if value is None else UnitStatus(value)


class QuantityType(TypeDecorator[Quantity]):
    """A non-negative count, stored as an integer. The `>= 0` floor is the value's own, and
    the balance columns repeat it as a CHECK so the database guards it too."""

    impl = Integer
    cache_ok = True  # SQLAlchemy checks each class itself, not the base

    @override
    def process_bind_param(self, value: Quantity | None, dialect: Dialect) -> int | None:
        return None if value is None else int(value)

    @override
    def process_result_value(self, value: int | None, dialect: Dialect) -> Quantity | None:
        return None if value is None else Quantity(value)
