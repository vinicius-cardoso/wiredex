import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from typing import NewType
from uuid import UUID

from wiredex.catalog.domain.errors import InvalidNumberError, InvalidUnitError

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
