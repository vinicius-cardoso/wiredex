"""What the catalog takes and gives over HTTP, in primitives only.

No domain object reaches a field: the `from_*` classmethods do the converting, as
identity's do. Attribute values are the one thing with two shapes on purpose — a request
carries whatever the owner typed, a response carries the stored value, its engineering
notation and its unit (design §6, requirements 3.9 and 3.10).
"""

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, Field

from wiredex.catalog.application.attributes import CategorySchema
from wiredex.catalog.application.categories import CategoryNode
from wiredex.catalog.application.parts import PartView
from wiredex.catalog.application.ports import Page
from wiredex.catalog.domain.category import Category
from wiredex.catalog.domain.errors import InvalidPinoutError, PinField
from wiredex.catalog.domain.notation import format_si
from wiredex.catalog.domain.part import PartDefinition
from wiredex.catalog.domain.pinout import Pin, Pinout, PinType, VoltageLevel
from wiredex.catalog.domain.schema import (
    AttributeDefinition,
    AttributeProblem,
    AttributeSchema,
    AttributeValues,
)
from wiredex.catalog.domain.values import AttributeKey, SiValue, Unit

# The kinds and problem names spelled out for the wire, so the generated client gets a
# union it can switch on. A test keeps each list in step with the enum it mirrors.
type AttributeKindName = Literal["number", "enum", "text", "bool"]
type AttributeProblemName = Literal[
    "missing_required", "wrong_kind", "not_in_options", "unknown_key"
]
# The same, for pins: the eight types a stored pin comes back as, and the five cells a
# refused table can point at.
type PinTypeName = Literal["power", "ground", "io", "input", "output", "analog", "nc", "other"]
type PinFieldName = Literal["number", "label", "type", "functions", "voltage"]

# What a request may carry for one attribute, before the schema says what it means. A
# string is the usual one ("4k7"), a bool is a switch, and null is nothing sent.
type RawAttributeValue = str | bool | int | float | None


class CreateCategoryRequest(BaseModel):
    name: str
    # No parent makes it a root category (requirements 1.1, 1.2).
    parent_id: UUID | None = None


class UpdateCategoryRequest(BaseModel):
    """A rename, a move, or both. What the body left out is left alone.

    `parent_id: null` is a move to the root, which is a different thing from not sending
    it, so the handler asks `moves()` rather than reading the value.
    """

    name: str | None = None
    parent_id: UUID | None = None

    def moves(self) -> bool:
        return "parent_id" in self.model_fields_set


class DefineAttributeRequest(BaseModel):
    key: str
    label: str
    kind: AttributeKindName
    # The SI symbol the numbers are stored in. It labels values; it never converts them.
    unit: str | None = None
    required: bool = False
    options: list[str] = Field(default_factory=list)
    position: int = 0


class UpdateAttributeRequest(BaseModel):
    """Label, required, options and position. `key` and `kind` are refused (requirement 2.9)."""

    label: str | None = None
    required: bool | None = None
    options: list[str] | None = None
    position: int | None = None
    key: str | None = None
    kind: AttributeKindName | None = None


class DefinePartRequest(BaseModel):
    category_id: UUID
    name: str
    # Keyed by attribute key, holding what was typed: "4k7" stays "4k7" until the
    # category's schema reads it.
    attributes: dict[str, RawAttributeValue] = Field(default_factory=dict)
    manufacturer: str | None = None
    mpn: str | None = None
    package: str | None = None


class UpdatePartRequest(BaseModel):
    """Replaces the details and the whole attribute map (requirement 4.8).

    `category_id` left out keeps the part where it is; sent, it moves the part and the
    values are validated against the new category's schema (requirement 4.10).
    """

    name: str
    attributes: dict[str, RawAttributeValue] = Field(default_factory=dict)
    manufacturer: str | None = None
    mpn: str | None = None
    package: str | None = None
    category_id: UUID | None = None


class PinRequest(BaseModel):
    """One row of a pin table, every cell as the owner typed or pasted it.

    Nothing here is checked beyond being text, on purpose, `type` included: the domain is
    the one authority on what a pin number or a voltage is, and it is the only thing that
    can say which row and which cell a refusal is about (requirement 3.1). A `Literal` on
    `type` would answer a pasted `GPIO` with a validation error naming neither.
    """

    number: str
    label: str
    type: str
    functions: list[str] = Field(default_factory=list)
    # As printed: "3V3", "3.3", "500mV". Nothing typed is a pin with no level (2.11).
    voltage: str | None = None


class ReplacePinoutRequest(BaseModel):
    """The part's whole pinout, because a pinout is replaced and never patched (design §2).

    No pins at all is a table cleared, not a body left out, so the field has a default and
    `{"pins": []}` and `{}` mean the same thing (requirement 1.4).
    """

    pins: list[PinRequest] = Field(default_factory=list)


class CategoryResponse(BaseModel):
    id: UUID
    parent_id: UUID | None
    name: str
    created_at: datetime

    @classmethod
    def from_category(cls, category: Category) -> Self:
        return cls(
            id=category.id,
            parent_id=category.parent_id,
            name=category.name.value,
            created_at=category.created_at,
        )


class CategoryNodeResponse(CategoryResponse):
    """A category as the tree shows it, with the counts requirement 1.11 asks for."""

    child_count: int
    part_count: int

    @classmethod
    def from_node(cls, node: CategoryNode) -> Self:
        category = CategoryResponse.from_category(node.category)
        return cls(
            **category.model_dump(),
            child_count=node.child_count,
            part_count=node.part_count,
        )


class AttributeResponse(BaseModel):
    id: UUID
    category_id: UUID
    key: str
    label: str
    kind: AttributeKindName
    unit: str | None
    required: bool
    options: list[str]
    position: int

    @classmethod
    def from_definition(cls, definition: AttributeDefinition) -> Self:
        return cls(
            id=definition.id,
            category_id=definition.category_id,
            key=definition.key.value,
            label=definition.label.value,
            kind=_kind_name(definition),
            unit=_unit_text(definition.unit),
            required=definition.required,
            options=list(definition.options),
            position=definition.position,
        )


class SchemaAttributeResponse(AttributeResponse):
    """A field of a resolved schema, marked when it comes from a category above this one."""

    inherited: bool

    @classmethod
    def from_inherited(cls, definition: AttributeDefinition, category: Category) -> Self:
        field = AttributeResponse.from_definition(definition)
        return cls(**field.model_dump(), inherited=definition.category_id != category.id)


class CategorySchemaResponse(BaseModel):
    """Every field a category's parts have, its ancestors' included (requirement 2.7)."""

    category: CategoryResponse
    attributes: list[SchemaAttributeResponse]

    @classmethod
    def from_schema(cls, resolved: CategorySchema) -> Self:
        category = resolved.category
        return cls(
            category=CategoryResponse.from_category(category),
            attributes=[
                SchemaAttributeResponse.from_inherited(definition, category)
                for definition in resolved.schema
            ],
        )


class AttributeValueResponse(BaseModel):
    """One stored value, in the three forms the web needs (requirements 3.9, 3.10).

    `value` is the exact stored value, a string for a number because JSON numbers are
    doubles in every client we generate and exactness is the whole point. `display` is the
    same number in engineering notation, so 4700 reads as `4.7k`, and `unit` labels it.
    """

    value: str | bool
    display: str
    unit: str | None

    @classmethod
    def from_stored(cls, value: object, unit: Unit | None) -> Self:
        if isinstance(value, SiValue):
            # Without the symbol: the unit travels in its own field, so the web can show
            # "4.7k Ω" or "4.7k" as it likes.
            return cls(value=str(value), display=format_si(value), unit=_unit_text(unit))
        if isinstance(value, bool):
            return cls(value=value, display="true" if value else "false", unit=_unit_text(unit))
        return cls(value=str(value), display=str(value), unit=_unit_text(unit))


class AttributeProblemResponse(BaseModel):
    """One attribute of a part that no longer fits its schema (requirement 5.3)."""

    key: str
    problem: AttributeProblemName
    message: str

    @classmethod
    def from_problem(cls, problem: AttributeProblem) -> Self:
        return cls(
            key=problem.key.value,
            problem=_problem_name(problem),
            message=problem.message,
        )


class PartSummaryResponse(BaseModel):
    """A part as the list shows it: no attribute values, because a page of rows must not
    resolve one schema per row (requirement 8.2)."""

    id: UUID
    category_id: UUID
    name: str
    manufacturer: str | None
    mpn: str | None
    package: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_part(cls, part: PartDefinition) -> Self:
        return cls(
            id=part.id,
            category_id=part.category_id,
            name=part.name.value,
            manufacturer=_text(part.manufacturer),
            mpn=_text(part.mpn),
            package=_text(part.package),
            created_at=part.created_at,
            updated_at=part.updated_at,
        )


class PartPageResponse(BaseModel):
    """One window of the list and the cursor the next one starts from (requirement 4.11)."""

    items: list[PartSummaryResponse]
    next_cursor: UUID | None

    @classmethod
    def from_page(cls, page: Page[PartDefinition]) -> Self:
        return cls(
            items=[PartSummaryResponse.from_part(part) for part in page.items],
            next_cursor=page.next_cursor,
        )


class PartResponse(PartSummaryResponse):
    """One part with its values, and whatever no longer fits its schema (requirement 5.2).

    A value stored under a key nothing defines any more is still here, with no unit: it is
    listed as a problem, never dropped (design §2.5).
    """

    attributes: dict[str, AttributeValueResponse]
    needs_review: bool
    problems: list[AttributeProblemResponse]
    # How many pins the part has, so a part page can say "no pinout yet" without asking for
    # the table (requirement 1.8). A part just defined has none, which is what 0 says.
    pin_count: int

    @classmethod
    def from_view(cls, view: PartView, schema: AttributeSchema) -> Self:
        summary = PartSummaryResponse.from_part(view.part)
        return cls(
            **summary.model_dump(),
            attributes=_values(view.part.attributes, schema),
            needs_review=view.needs_review,
            problems=[AttributeProblemResponse.from_problem(p) for p in view.problems],
            pin_count=view.pin_count,
        )


class VoltageResponse(BaseModel):
    """A pin's stored level in the two forms requirement 2.13 asks for.

    A string and not a JSON number, for the reason `AttributeValueResponse.value` is one:
    JSON numbers are doubles in every client we generate, and the level is exact.
    """

    value: str
    display: str

    @classmethod
    def from_level(cls, voltage: VoltageLevel) -> Self:
        return cls(value=str(voltage), display=voltage.display())


class PinResponse(BaseModel):
    """One stored pin. `number` comes back upper-cased and `voltage` in volts, whatever
    was typed: normalizing is the domain's, and this is what it kept (requirements 2.1, 2.9)."""

    number: str
    label: str
    type: PinTypeName
    functions: list[str]
    voltage: VoltageResponse | None

    @classmethod
    def from_pin(cls, pin: Pin) -> Self:
        return cls(
            number=str(pin.number),
            label=str(pin.label),
            type=_pin_type_name(pin.type),
            functions=[str(function) for function in pin.functions],
            voltage=None if pin.voltage is None else VoltageResponse.from_level(pin.voltage),
        )


class PinoutResponse(BaseModel):
    """A part's pins in their saved order; `[]` for a part with none, never a 404 (1.2)."""

    pins: list[PinResponse]

    @classmethod
    def from_pinout(cls, pinout: Pinout) -> Self:
        return cls(pins=[PinResponse.from_pin(pin) for pin in pinout])


class PinoutRefusalResponse(BaseModel):
    """The `detail` of a refused pin table (requirements 3.1 to 3.3).

    Every other catalog refusal is a sentence, and the part form finds the field it is about
    by the attribute name in it. Forty rows can't be read that way, so this one carries the
    row and the cell as data and the editor marks them. Both are null when the pinout is
    refused as a whole, as too many pins is.
    """

    message: str
    row: int | None
    field: PinFieldName | None

    @classmethod
    def from_error(cls, error: InvalidPinoutError) -> Self:
        return cls(message=str(error), row=error.row, field=_pin_field_name(error.field))


def _values(values: AttributeValues, schema: AttributeSchema) -> dict[str, AttributeValueResponse]:
    return {
        key.value: AttributeValueResponse.from_stored(value, _unit_of(schema, key))
        for key, value in values.items()
    }


def _unit_of(schema: AttributeSchema, key: AttributeKey) -> Unit | None:
    definition = schema.get(key)
    return None if definition is None else definition.unit


def _kind_name(definition: AttributeDefinition) -> AttributeKindName:
    # An enum's value is the literal it holds, so a fifth kind stops type-checking here
    # until the wire contract above lists it too.
    name: AttributeKindName = definition.kind.value
    return name


def _problem_name(problem: AttributeProblem) -> AttributeProblemName:
    name: AttributeProblemName = problem.problem.value
    return name


def _pin_type_name(kind: PinType) -> PinTypeName:
    # As `_kind_name` does: a ninth pin type stops type-checking here until the wire
    # contract above lists it too.
    name: PinTypeName = kind.value
    return name


def _pin_field_name(field: PinField | None) -> PinFieldName | None:
    if field is None:
        return None
    name: PinFieldName = field.value
    return name


def _unit_text(unit: Unit | None) -> str | None:
    return None if unit is None else unit.value


def _text(value: object) -> str | None:
    return None if value is None else str(value)
