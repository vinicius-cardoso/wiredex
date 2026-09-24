"""Column types that store identity value objects as plain columns and read them back."""

from collections.abc import Callable
from typing import Protocol, override

from sqlalchemy import Dialect, String, TypeDecorator

from wiredex.identity.domain.values import MAX_EMAIL_LENGTH, Email, Name, PasswordHash


class _HasStrValue(Protocol):
    @property
    def value(self) -> str: ...


class _StrValueObjectType[V: _HasStrValue](TypeDecorator[V]):
    """A value object with a single `value: str`, stored as that string."""

    impl = String(255)  # each subclass sets its own length
    cache_ok = True
    rebuild: Callable[[str], V]

    @override
    def process_bind_param(self, value: V | None, dialect: Dialect) -> str | None:
        return None if value is None else value.value

    @override
    def process_result_value(self, value: str | None, dialect: Dialect) -> V | None:
        return None if value is None else type(self).rebuild(value)


class EmailType(_StrValueObjectType[Email]):
    impl = String(MAX_EMAIL_LENGTH)
    rebuild = Email
    cache_ok = True  # SQLAlchemy checks each class itself, not the base


class NameType(_StrValueObjectType[Name]):
    impl = String(80)
    rebuild = Name
    cache_ok = True  # SQLAlchemy checks each class itself, not the base


class PasswordHashType(_StrValueObjectType[PasswordHash]):
    impl = String(255)
    rebuild = PasswordHash
    cache_ok = True  # SQLAlchemy checks each class itself, not the base
