import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import NewType
from uuid import UUID

from wiredex.catalog.domain.errors import (
    CatalogError,
    InvalidAttributeKeyError,
    InvalidLabelError,
    InvalidNameError,
    InvalidNumberError,
    InvalidPartDetailError,
    InvalidUnitError,
)

# Catalog declares its own WorkspaceId instead of importing identity's: modules don't
# import each other's domain. Promote it to the shared kernel when a third module needs it.
WorkspaceId = NewType("WorkspaceId", UUID)
CategoryId = NewType("CategoryId", UUID)
AttributeDefinitionId = NewType("AttributeDefinitionId", UUID)
PartDefinitionId = NewType("PartDefinitionId", UUID)

MAX_UNIT_LENGTH = 16


@dataclass(frozen=True, slots=True)
class Unit:
    """The SI symbol a number attribute is stored in (Ω, F, V, Hz). It labels, it never converts."""

    value: str

    def __post_init__(self) -> None:
        # NFKC, as parse_si does, so an Ω typed as the ohm sign matches one typed as omega.
        trimmed = unicodedata.normalize("NFKC", self.value).strip()
        if not 1 <= len(trimmed) <= MAX_UNIT_LENGTH:
            raise InvalidUnitError(f"a unit needs between 1 and {MAX_UNIT_LENGTH} characters")
        object.__setattr__(self, "value", trimmed)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class SiValue:
    """A number attribute in SI base units: Decimal, so 10k and 10000 compare exactly equal."""

    value: Decimal

    def __post_init__(self) -> None:
        if not self.value.is_finite():
            raise InvalidNumberError(f"{self.value} is not a finite number")

    def __str__(self) -> str:
        # Plain digits, never 1E-7: this text is what crosses the wire and reaches JSONB.
        return f"{self.value:f}"


def _capped(text: str, cap: int, what: str, error: type[CatalogError]) -> str:
    """Trims, collapses inner runs of whitespace, and refuses empty or over-long text.

    The text values below differ only in their cap and their error, so the rule lives here.
    """
    collapsed = " ".join(text.split())
    if not 1 <= len(collapsed) <= cap:
        raise error(f"{what} needs between 1 and {cap} characters")
    return collapsed


MAX_CATEGORY_NAME_LENGTH = 80


@dataclass(frozen=True, slots=True)
class CategoryName:
    """A category's name, kept as cased: *Thick film* is the owner's spelling, not noise."""

    value: str

    def __post_init__(self) -> None:
        name = _capped(self.value, MAX_CATEGORY_NAME_LENGTH, "a category name", InvalidNameError)
        object.__setattr__(self, "value", name)

    def __str__(self) -> str:
        return self.value


MAX_PART_NAME_LENGTH = 120


@dataclass(frozen=True, slots=True)
class PartName:
    """What the part is called, roomier than a category name because datasheet names are long."""

    value: str

    def __post_init__(self) -> None:
        name = _capped(self.value, MAX_PART_NAME_LENGTH, "a part name", InvalidNameError)
        object.__setattr__(self, "value", name)

    def __str__(self) -> str:
        return self.value


MAX_ATTRIBUTE_KEY_LENGTH = 40
# A slug, because the key names a JSONB field and will be a query identifier: lower-case
# letters first, then letters, digits and underscores.
_ATTRIBUTE_KEY = re.compile(rf"^[a-z][a-z0-9_]{{0,{MAX_ATTRIBUTE_KEY_LENGTH - 1}}}$")


@dataclass(frozen=True, slots=True)
class AttributeKey:
    """The identifier an attribute is stored under, lower-cased so `Resistance` finds it too."""

    value: str

    def __post_init__(self) -> None:
        key = self.value.strip().lower()
        if not _ATTRIBUTE_KEY.match(key):
            raise InvalidAttributeKeyError(
                f"{self.value!r} is not a key like resistance: a letter, then letters, "
                f"digits or _, up to {MAX_ATTRIBUTE_KEY_LENGTH} characters"
            )
        object.__setattr__(self, "value", key)

    def __str__(self) -> str:
        return self.value


MAX_ATTRIBUTE_LABEL_LENGTH = 80


@dataclass(frozen=True, slots=True)
class AttributeLabel:
    """What the form shows above the field, in the owner's own words and casing."""

    value: str

    def __post_init__(self) -> None:
        label = _capped(
            self.value, MAX_ATTRIBUTE_LABEL_LENGTH, "an attribute label", InvalidLabelError
        )
        object.__setattr__(self, "value", label)

    def __str__(self) -> str:
        return self.value


class AttributeKind(StrEnum):
    """ADR 0005's four kinds. A fifth one means a new member and a new validator, nothing else."""

    NUMBER = "number"
    ENUM = "enum"
    TEXT = "text"
    BOOL = "bool"


MAX_MANUFACTURER_LENGTH = 80


@dataclass(frozen=True, slots=True)
class Manufacturer:
    """Who makes the part. Free text: a manufacturer registry is not worth its upkeep here."""

    value: str

    def __post_init__(self) -> None:
        name = _capped(
            self.value, MAX_MANUFACTURER_LENGTH, "a manufacturer", InvalidPartDetailError
        )
        object.__setattr__(self, "value", name)

    def __str__(self) -> str:
        return self.value


MAX_MPN_LENGTH = 80


@dataclass(frozen=True, slots=True)
class Mpn:
    """A manufacturer part number, kept as printed on the part."""

    value: str

    def __post_init__(self) -> None:
        mpn = _capped(self.value, MAX_MPN_LENGTH, "an MPN", InvalidPartDetailError)
        object.__setattr__(self, "value", mpn)

    def fold(self) -> str:
        """The form uniqueness compares on: lower(), the function the partial index uses too."""
        return self.value.lower()

    def __str__(self) -> str:
        return self.value


MAX_PACKAGE_LENGTH = 40


@dataclass(frozen=True, slots=True)
class Package:
    """The footprint or case: 0805, SOT-23, DIP-8. Short, because package names are short."""

    value: str

    def __post_init__(self) -> None:
        package = _capped(self.value, MAX_PACKAGE_LENGTH, "a package", InvalidPartDetailError)
        object.__setattr__(self, "value", package)

    def __str__(self) -> str:
        return self.value
