"""Column types that store firmware's value objects as plain columns and read them back.

The pattern catalog, inventory, identity and projects use for their own values. They aren't
shared because modules don't import each other (ADR 0001).
"""

from collections.abc import Callable
from typing import Any, Protocol, override

from sqlalchemy import Dialect, String, Text, TypeDecorator
from sqlalchemy.sql.operators import OperatorType
from sqlalchemy.types import TypeEngine

from wiredex.firmware.domain.semver import MAX_VERSION_LENGTH, SemVer
from wiredex.firmware.domain.source import MAX_PATH_LENGTH, SourcePath, SourceText
from wiredex.firmware.domain.values import (
    MAX_NAME_LENGTH,
    MAX_TARGET_LENGTH,
    MAX_TEXT_LENGTH,
    BoardTarget,
    Changelog,
    Description,
    FirmwareName,
)


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


class FirmwareNameType(_StrValueObjectType[FirmwareName]):
    impl = String(MAX_NAME_LENGTH)
    rebuild = FirmwareName
    cache_ok = True  # SQLAlchemy checks each class itself, not the base


class BoardTargetType(_StrValueObjectType[BoardTarget]):
    impl = String(MAX_TARGET_LENGTH)
    rebuild = BoardTarget
    cache_ok = True  # SQLAlchemy checks each class itself, not the base


class DescriptionType(_StrValueObjectType[Description]):
    impl = String(MAX_TEXT_LENGTH)
    rebuild = Description
    cache_ok = True  # SQLAlchemy checks each class itself, not the base


class ChangelogType(_StrValueObjectType[Changelog]):
    impl = String(MAX_TEXT_LENGTH)
    rebuild = Changelog
    cache_ok = True  # SQLAlchemy checks each class itself, not the base


class SourcePathType(_StrValueObjectType[SourcePath]):
    """A path as its normalized text, NFC with `/` between its parts (decision 9), which the
    unique index folds with `lower()` as `SourcePath.fold` does."""

    impl = String(MAX_PATH_LENGTH)
    rebuild = SourcePath
    cache_ok = True  # SQLAlchemy checks each class itself, not the base


class SourceTextType(_StrValueObjectType[SourceText]):
    """A file's text in a `text` column, uncapped there: a version's 1,048,576 bytes are the
    domain's to count (decision 9), and each row's `size` CHECK ties the stored size to it."""

    impl = Text()
    rebuild = SourceText
    cache_ok = True  # SQLAlchemy checks each class itself, not the base


class SemVerType(TypeDecorator[SemVer]):
    """A version number as its canonical text, `1.3.0-rc.1`: lower-cased and without a `v`, so
    the column holds each number one way and its unique index needs no `lower()` (decision 6).

    Read back through `SemVer.parse`. The text orders numbers as text does, `1.10.0` before
    `1.2.0`, so no query sorts on it: `FirmwareVersions` sorts by precedence.
    """

    impl = String(MAX_VERSION_LENGTH)
    cache_ok = True  # SQLAlchemy checks each class itself, not the base

    @override
    def process_bind_param(self, value: SemVer | None, dialect: Dialect) -> str | None:
        return None if value is None else str(value)

    @override
    def process_result_value(self, value: str | None, dialect: Dialect) -> SemVer | None:
        return None if value is None else SemVer.parse(value)
