"""One validator per attribute kind: raw input in, the value the catalog stores out.

Strategy, selected by `VALIDATORS`, so a fifth kind is a new member and a new validator
and nothing else — the Open/Closed line in `docs/architecture.md`. Every rejection names
the attribute, because the API answers 422 per field.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from wiredex.catalog.domain.errors import CatalogError, InvalidNumberError
from wiredex.catalog.domain.notation import parse_si
from wiredex.catalog.domain.values import AttributeKey, AttributeKind, SiValue, Unit

MAX_TEXT_LENGTH = 500


class AttributeSpec(Protocol):
    """What validation reads off an attribute: its key, its kind, its unit, its options.

    Structural on purpose. `schema.AttributeDefinition` satisfies it by having these four,
    so the dependency points one way — schema uses validators, validators know no schema.
    """

    # Read-only properties, as identity's ports: a protocol attribute would have to be
    # matched by an attribute, ruling out a definition that computes any of these.
    @property
    def key(self) -> AttributeKey: ...

    @property
    def kind(self) -> AttributeKind: ...

    @property
    def unit(self) -> Unit | None: ...

    @property
    def options(self) -> tuple[str, ...]: ...


class AttributeValidator(Protocol):
    def coerce(self, definition: AttributeSpec, raw: object) -> object:
        """The value to store, or a `CatalogError` naming the attribute and what it takes."""
        ...


@dataclass(frozen=True, slots=True)
class NumberValidator:
    """Engineering notation read in the attribute's unit: 100nF on a farad, never 100nH."""

    def coerce(self, definition: AttributeSpec, raw: object) -> SiValue:
        text = _as_number_text(raw)
        if text is None:
            raise InvalidNumberError(f"{definition.key} takes a number, not {_kind_of(raw)}")
        try:
            return parse_si(text, definition.unit)
        except InvalidNumberError as error:
            # parse_si explains the spelling and the unit; only the key is missing from it.
            raise InvalidNumberError(f"{definition.key}: {error}") from error


@dataclass(frozen=True, slots=True)
class EnumValidator:
    """One of the definition's options, spelled as the definition spells it."""

    def coerce(self, definition: AttributeSpec, raw: object) -> str:
        if isinstance(raw, str) and raw in definition.options:
            return raw
        options = ", ".join(definition.options)
        raise CatalogError(f"{definition.key} takes one of {options} — not {raw!r}")


@dataclass(frozen=True, slots=True)
class TextValidator:
    """Free text, trimmed and capped: an attribute value is a note, not a datasheet."""

    def coerce(self, definition: AttributeSpec, raw: object) -> str:
        if not isinstance(raw, str):
            raise CatalogError(f"{definition.key} takes text, not {_kind_of(raw)}")
        text = raw.strip()
        if len(text) > MAX_TEXT_LENGTH:
            raise CatalogError(f"{definition.key} takes at most {MAX_TEXT_LENGTH} characters")
        return text


@dataclass(frozen=True, slots=True)
class BoolValidator:
    """A real boolean. The client sends JSON, so "true" is a string and a mistake."""

    def coerce(self, definition: AttributeSpec, raw: object) -> bool:
        if not isinstance(raw, bool):
            raise CatalogError(f"{definition.key} takes true or false, not {raw!r}")
        return raw


VALIDATORS: Mapping[AttributeKind, AttributeValidator] = {
    AttributeKind.NUMBER: NumberValidator(),
    AttributeKind.ENUM: EnumValidator(),
    AttributeKind.TEXT: TextValidator(),
    AttributeKind.BOOL: BoolValidator(),
}


def _as_number_text(raw: object) -> str | None:
    """The one text parse_si reads, or None when the input was never a number."""
    # bool before int, because a bool is an int in Python and a switch is not a number.
    if isinstance(raw, bool):
        return None
    if isinstance(raw, str):
        return raw
    if isinstance(raw, int | Decimal):
        return str(raw)
    if isinstance(raw, float):
        # repr's shortest round trip, so 0.1 reads as 0.1 and not as 0.1000000000000000055.
        return repr(raw)
    return None


def _kind_of(raw: object) -> str:
    return "nothing" if raw is None else type(raw).__name__
