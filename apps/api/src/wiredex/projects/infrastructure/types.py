"""Column types that store projects' value objects as plain columns and read them back.

The pattern catalog, inventory and identity use for their own values. They aren't shared
because modules don't import each other (ADR 0001).
"""

from collections.abc import Callable
from typing import Any, Protocol, override

from sqlalchemy import Dialect, Integer, String, TypeDecorator
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.sql.operators import OperatorType
from sqlalchemy.types import TypeEngine

from wiredex.projects.domain.bom import MAX_NOTES_LENGTH, BomNotes, LineQuantity
from wiredex.projects.domain.designators import MAX_DESIGNATOR_LETTERS, Designator
from wiredex.projects.domain.netlist import (
    MAX_NET_NAME_LENGTH,
    MAX_NET_NOTES_LENGTH,
    NetName,
    NetNotes,
)
from wiredex.projects.domain.pins import MAX_PIN_NUMBER_LENGTH, PinNumber
from wiredex.projects.domain.values import (
    MAX_LABEL_LENGTH,
    MAX_PROJECT_NAME_LENGTH,
    MAX_SUMMARY_LENGTH,
    MAX_TAG_LENGTH,
    MAX_TEXT_LENGTH,
    Description,
    Notes,
    ProjectName,
    RevisionLabel,
    Summary,
    Tags,
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


class ProjectNameType(_StrValueObjectType[ProjectName]):
    impl = String(MAX_PROJECT_NAME_LENGTH)
    rebuild = ProjectName
    cache_ok = True  # SQLAlchemy checks each class itself, not the base


class DescriptionType(_StrValueObjectType[Description]):
    impl = String(MAX_TEXT_LENGTH)
    rebuild = Description
    cache_ok = True  # SQLAlchemy checks each class itself, not the base


class NotesType(_StrValueObjectType[Notes]):
    impl = String(MAX_TEXT_LENGTH)
    rebuild = Notes
    cache_ok = True  # SQLAlchemy checks each class itself, not the base


class SummaryType(_StrValueObjectType[Summary]):
    impl = String(MAX_SUMMARY_LENGTH)
    rebuild = Summary
    cache_ok = True  # SQLAlchemy checks each class itself, not the base


class RevisionLabelType(_StrValueObjectType[RevisionLabel]):
    impl = String(MAX_LABEL_LENGTH)
    rebuild = RevisionLabel
    cache_ok = True  # SQLAlchemy checks each class itself, not the base


class BomNotesType(_StrValueObjectType[BomNotes]):
    impl = String(MAX_NOTES_LENGTH)
    rebuild = BomNotes
    cache_ok = True  # SQLAlchemy checks each class itself, not the base


class DesignatorType(TypeDecorator[Designator]):
    """A designator as its canonical text, `R1`: eight letters and four digits at most.

    Read back through `Designator.parse`, and written canonical, which is what the column's
    CHECK accepts, so a join on it (11's pin references) never has to fold.
    """

    impl = String(MAX_DESIGNATOR_LETTERS + 4)
    cache_ok = True  # SQLAlchemy checks each class itself, not the base

    @override
    def process_bind_param(self, value: Designator | None, dialect: Dialect) -> str | None:
        return None if value is None else str(value)

    @override
    def process_result_value(self, value: str | None, dialect: Dialect) -> Designator | None:
        return None if value is None else Designator.parse(value)


class NetNameType(_StrValueObjectType[NetName]):
    impl = String(MAX_NET_NAME_LENGTH)
    rebuild = NetName
    cache_ok = True  # SQLAlchemy checks each class itself, not the base


class NetNotesType(_StrValueObjectType[NetNotes]):
    impl = String(MAX_NET_NOTES_LENGTH)
    rebuild = NetNotes
    cache_ok = True  # SQLAlchemy checks each class itself, not the base


class PinNumberType(_StrValueObjectType[PinNumber]):
    """A pin number as its normalized text, which the column's CHECK accepts (11's decision 2)."""

    impl = String(MAX_PIN_NUMBER_LENGTH)
    rebuild = PinNumber
    cache_ok = True  # SQLAlchemy checks each class itself, not the base


class LineQuantityType(TypeDecorator[LineQuantity]):
    """A line's quantity as a plain integer, which the report and `uses_of` can sum."""

    impl = Integer
    cache_ok = True  # SQLAlchemy checks each class itself, not the base

    @override
    def process_bind_param(self, value: LineQuantity | None, dialect: Dialect) -> int | None:
        return None if value is None else value.value

    @override
    def process_result_value(self, value: int | None, dialect: Dialect) -> LineQuantity | None:
        return None if value is None else LineQuantity(value)


class TagsType(TypeDecorator[Tags]):
    """A project's tags as a `varchar(32)[]`, like `pins.functions`: a flat list of short
    strings, which `tags @> ARRAY[…]` filters through a GIN index.

    Stored in `Tags`' own order, alphabetical, and read back through `Tags.of`, so a row
    compares equal to the value it was written from.
    """

    impl = ARRAY(String(MAX_TAG_LENGTH))
    cache_ok = True  # SQLAlchemy checks each class itself, not the base

    @override
    def process_bind_param(self, value: Tags | None, dialect: Dialect) -> list[str] | None:
        return None if value is None else list(value.texts())

    @override
    def process_result_value(self, value: list[str] | None, dialect: Dialect) -> Tags | None:
        return None if value is None else Tags.of(value)
