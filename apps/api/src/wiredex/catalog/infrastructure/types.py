"""Column types that store catalog value objects as plain columns and read them back.

Identity has the same pattern for its own values. The two aren't shared because modules
don't import each other (ADR 0001); promote it to the shared kernel when a third module
needs it, as `WorkspaceId` will be.
"""

from collections.abc import Callable, Mapping
from decimal import Decimal
from typing import Protocol, override

from sqlalchemy import Dialect, String, TypeDecorator
from sqlalchemy.dialects.postgresql import JSONB

from wiredex.catalog.domain.schema import AttributeValues
from wiredex.catalog.domain.values import (
    MAX_ATTRIBUTE_KEY_LENGTH,
    MAX_ATTRIBUTE_LABEL_LENGTH,
    MAX_CATEGORY_NAME_LENGTH,
    MAX_MANUFACTURER_LENGTH,
    MAX_MPN_LENGTH,
    MAX_PACKAGE_LENGTH,
    MAX_PART_NAME_LENGTH,
    MAX_UNIT_LENGTH,
    AttributeKey,
    AttributeLabel,
    CategoryName,
    Manufacturer,
    Mpn,
    Package,
    PartName,
    SiValue,
    Unit,
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
    def process_bind_param(self, value: V | None, dialect: Dialect) -> str | None:
        return None if value is None else value.value

    @override
    def process_result_value(self, value: str | None, dialect: Dialect) -> V | None:
        return None if value is None else type(self).rebuild(value)


class CategoryNameType(_StrValueObjectType[CategoryName]):
    impl = String(MAX_CATEGORY_NAME_LENGTH)
    rebuild = CategoryName
    cache_ok = True  # SQLAlchemy checks each class itself, not the base


class AttributeKeyType(_StrValueObjectType[AttributeKey]):
    impl = String(MAX_ATTRIBUTE_KEY_LENGTH)
    rebuild = AttributeKey
    cache_ok = True  # SQLAlchemy checks each class itself, not the base


class AttributeLabelType(_StrValueObjectType[AttributeLabel]):
    impl = String(MAX_ATTRIBUTE_LABEL_LENGTH)
    rebuild = AttributeLabel
    cache_ok = True  # SQLAlchemy checks each class itself, not the base


class UnitType(_StrValueObjectType[Unit]):
    impl = String(MAX_UNIT_LENGTH)
    rebuild = Unit
    cache_ok = True  # SQLAlchemy checks each class itself, not the base


class PartNameType(_StrValueObjectType[PartName]):
    impl = String(MAX_PART_NAME_LENGTH)
    rebuild = PartName
    cache_ok = True  # SQLAlchemy checks each class itself, not the base


class ManufacturerType(_StrValueObjectType[Manufacturer]):
    impl = String(MAX_MANUFACTURER_LENGTH)
    rebuild = Manufacturer
    cache_ok = True  # SQLAlchemy checks each class itself, not the base


class MpnType(_StrValueObjectType[Mpn]):
    impl = String(MAX_MPN_LENGTH)
    rebuild = Mpn
    cache_ok = True  # SQLAlchemy checks each class itself, not the base


class PackageType(_StrValueObjectType[Package]):
    impl = String(MAX_PACKAGE_LENGTH)
    rebuild = Package
    cache_ok = True  # SQLAlchemy checks each class itself, not the base


class AttributeOptionsType(TypeDecorator[tuple[str, ...]]):
    """A choice attribute's options: a JSONB list of strings, the domain's immutable tuple.

    A closed list owned by one definition and never queried on its own, so it stays in the
    row rather than becoming a table of its own (design §5).
    """

    impl = JSONB
    cache_ok = True  # SQLAlchemy checks each class itself, not the base

    @override
    def process_bind_param(
        self, value: tuple[str, ...] | None, dialect: Dialect
    ) -> list[str] | None:
        return None if value is None else list(value)

    @override
    def process_result_value(
        self, value: list[str] | None, dialect: Dialect
    ) -> tuple[str, ...] | None:
        return None if value is None else tuple(value)


class AttributeValuesType(TypeDecorator[AttributeValues]):
    """A part's attribute values, as a JSONB object of plain JSON types.

    Design §5 expected the repository to rebuild `AttributeValues` after a load instead of a
    type here, but it can't: SQLAlchemy writes whatever the mapped attribute holds, and the
    domain holds `SiValue`s, which no JSON serializer takes. Unwrapping has to happen on the
    way in, so rewrapping belongs on the way out, and both live here.

    No schema is needed for it either. The stored JSON type says which value is which: a
    number is the SI value of a number attribute, and text, choices and switches come back
    as they went in. Rewrapping matters because `PartDefinition.revise` compares the map it
    is given with the stored one, and a `Decimal` never equals the `SiValue` a validator
    just produced (requirement 4.9).
    """

    impl = JSONB
    cache_ok = True  # SQLAlchemy checks each class itself, not the base

    @override
    def process_bind_param(
        self, value: AttributeValues | None, dialect: Dialect
    ) -> dict[str, object] | None:
        if value is None:
            return None
        return {key.value: _stored(item) for key, item in value.items()}

    @override
    def process_result_value(
        self, value: Mapping[str, object] | None, dialect: Dialect
    ) -> AttributeValues | None:
        if value is None:
            return None
        return AttributeValues({AttributeKey(key): _restored(item) for key, item in value.items()})


def _stored(value: object) -> object:
    # The Decimal inside, which bootstrap.database writes as an exact JSON number (ADR 0005).
    return value.value if isinstance(value, SiValue) else value


def _restored(value: object) -> object:
    # bool before int, as the validators do it: in Python a bool is an int, and a switch
    # is not a number. A whole number reads back as int, a fractional one as Decimal.
    if isinstance(value, bool):
        return value
    if isinstance(value, int | Decimal):
        return SiValue(Decimal(value))
    return value
