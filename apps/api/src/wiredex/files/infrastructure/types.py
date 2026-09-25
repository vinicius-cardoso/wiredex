"""Column types that store files' value objects as plain columns and read them back.

The catalog and identity have the same pattern for their own values. The three aren't
shared because modules don't import each other (ADR 0001); promote it to the shared kernel
when the pattern is common enough, as `WorkspaceId` will be.
"""

from typing import Any, override

from sqlalchemy import Dialect, Integer, String, TypeDecorator
from sqlalchemy.sql.operators import OperatorType
from sqlalchemy.types import TypeEngine

from wiredex.files.domain.values import AttachmentTitle, FileSize, Sha256


class Sha256Type(TypeDecorator[Sha256]):
    """A file's content address, stored as its 64 hex characters."""

    impl = String(64)
    cache_ok = True

    @override
    def coerce_compared_value(self, op: OperatorType | None, value: Any) -> TypeEngine[Any]:
        # Plain text on the other side of a comparison stays plain text, as the catalog's
        # value types do: a query filtering on a raw hex string shouldn't be asked for `.value`.
        if isinstance(value, str):
            return String(64)
        return self

    @override
    def process_bind_param(self, value: Sha256 | None, dialect: Dialect) -> str | None:
        return None if value is None else value.value

    @override
    def process_result_value(self, value: str | None, dialect: Dialect) -> Sha256 | None:
        return None if value is None else Sha256(value)


class AttachmentTitleType(TypeDecorator[AttachmentTitle]):
    """An attachment's title, stored as its text."""

    impl = String(120)
    cache_ok = True

    @override
    def process_bind_param(self, value: AttachmentTitle | None, dialect: Dialect) -> str | None:
        return None if value is None else value.value

    @override
    def process_result_value(self, value: str | None, dialect: Dialect) -> AttachmentTitle | None:
        return None if value is None else AttachmentTitle(value)


class FileSizeType(TypeDecorator[FileSize]):
    """A file's size in bytes, stored as an integer."""

    impl = Integer
    cache_ok = True

    @override
    def process_bind_param(self, value: FileSize | None, dialect: Dialect) -> int | None:
        return None if value is None else value.value

    @override
    def process_result_value(self, value: int | None, dialect: Dialect) -> FileSize | None:
        return None if value is None else FileSize(value)
