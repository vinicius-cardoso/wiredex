"""A search specification compiled to one SQL predicate, one case per filter type.

The mirror of the domain's `matches` (search.py): the domain evaluates one part in Python,
this turns the same filter objects into a `WHERE` clause SQLAlchemy sends to Postgres, so a
search costs one query however many filters it carries (requirement 7.3). Keeping the two in
step is Property 1's job — the database and the domain must select the same parts.

Every key and every value is a **bound parameter**, never interpolated into the SQL text: an
attribute key names a JSONB field and reaches the query as data, so a key like `resistance`
can never carry SQL of its own. `%` and `_` in searched text are escaped, so they match those
characters and not "any run" or "any character" (requirement 1.5).

Numeric comparisons are guarded by `jsonb_typeof(...) = 'number'`, so a part holding text
where a number is expected after a schema change drops out of that filter instead of making
the whole query fail (requirement 2.7). Enum and boolean filters use `@>`, which the
attributes' GIN index serves (requirement 7.2); the text filters lean on the trigram indexes.
"""

from collections.abc import Callable
from decimal import Decimal
from typing import cast as type_cast

from sqlalchemy import ColumnElement, and_, case, cast, func, literal, or_, select, true
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import Numeric, Text

from wiredex.catalog.domain.search import (
    AllOf,
    HasPin,
    InCategories,
    IsBool,
    NumberBetween,
    OneOf,
    SearchText,
    Spec,
    TextAttributeContains,
    TextContains,
)
from wiredex.catalog.domain.values import AttributeKey
from wiredex.catalog.infrastructure.orm import part_definitions, pins

# `%` is "any run", `_` is "any character", `\` escapes both: someone searching "100%" or a
# part number with an underscore means the character, so all three are escaped and the escape
# is named to the operator. The order matters — the backslash goes first, or it would double
# the ones the wildcards just added.
_LIKE_WILDCARDS = str.maketrans({"\\": "\\\\", "%": "\\%", "_": "\\_"})
_LIKE_ESCAPE = "\\"


def compile_spec(spec: Spec) -> ColumnElement[bool]:
    """A filter as the SQL predicate it selects by, one small compiler per filter type.

    Dispatched on the concrete class, the same shape the domain's one-class-per-filter and
    the application's one-builder-per-kind have (`_BUILDERS`, `_SPEC_KEYS`): a new filter is
    a new class and a new entry in `_COMPILERS`, and no single function grows. A spec with no
    compiler is a programming error — a filter class added without its case — so it fails
    loudly rather than silently matching everything.
    """
    compiler = _COMPILERS.get(type(spec))
    if compiler is None:  # pragma: no cover  a new filter class must be added to _COMPILERS
        raise TypeError(f"no SQL for {spec!r}: every filter type needs a compile_spec case")
    return compiler(spec)


def _all_of(spec: AllOf) -> ColumnElement[bool]:
    # Every inner filter has to hold; an empty AllOf matches every part (requirements 2.6,
    # 3.2), which `true()` is — `and_()` with nothing would too, but `true()` says it.
    if not spec.specs:
        return true()
    return and_(*(compile_spec(inner) for inner in spec.specs))


def _text_contains(spec: TextContains) -> ColumnElement[bool]:
    # One bound pattern against each identifying column; the trigram indexes serve each ILIKE.
    pattern = _containing(spec.text)
    return or_(
        part_definitions.c.name.ilike(pattern, escape=_LIKE_ESCAPE),
        part_definitions.c.manufacturer.ilike(pattern, escape=_LIKE_ESCAPE),
        part_definitions.c.mpn.ilike(pattern, escape=_LIKE_ESCAPE),
        part_definitions.c.package.ilike(pattern, escape=_LIKE_ESCAPE),
    )


def _in_categories(spec: InCategories) -> ColumnElement[bool]:
    # `= ANY(:ids)`, one bound array, so any number of descendant categories is one parameter.
    category_ids = [str(category_id) for category_id in spec.category_ids]
    return part_definitions.c.category_id == func.any(literal(category_ids))


def _number_between(spec: NumberBetween) -> ColumnElement[bool]:
    # The value only when it is a JSON number: a part holding text or nothing for the key has
    # a NULL here and drops out, rather than a cast blowing up the query (requirement 2.7).
    number = number_value(spec.key)
    bounds: list[ColumnElement[bool]] = []
    if spec.minimum is not None:
        bounds.append(number >= _decimal(spec.minimum.value))
    if spec.maximum is not None:
        bounds.append(number <= _decimal(spec.maximum.value))
    # At least one bound exists (the domain refuses a range with neither), so `and_` is never
    # empty here; a NULL `number` fails every comparison, which is the wrong-kind part left out.
    return and_(*bounds)


def _one_of(spec: OneOf) -> ColumnElement[bool]:
    # `attributes @> {"key": option}` per option, ORed: the containment the GIN index serves
    # (requirement 7.2). Options are sorted so the SQL is stable for a given filter.
    return or_(*(_contains_pair(spec.key, option) for option in sorted(spec.options)))


def _is_bool(spec: IsBool) -> ColumnElement[bool]:
    # `attributes @> {"key": true|false}`, the GIN index again. A stored number or string
    # under the key doesn't contain the JSON boolean, so a wrong-kind value doesn't match.
    return _contains_pair(spec.key, spec.value)


def _text_attribute_contains(spec: TextAttributeContains) -> ColumnElement[bool]:
    # A string value, case-insensitively containing the fragment. The type guard first, so a
    # number or boolean under the key isn't fed to `->>` as text and mistaken for a match.
    value = _attribute(spec.key)
    return and_(
        func.jsonb_typeof(value) == literal("string"),
        _attribute_text(spec.key).ilike(_containing(spec.text), escape=_LIKE_ESCAPE),
    )


def _has_pin(spec: HasPin) -> ColumnElement[bool]:
    """A part with a pin whose label or one of its functions equals the name, ignoring case.

    An EXISTS over the part's pins, upper-casing both sides so the match is case-insensitive
    (requirement 3.1). `:P` is upper-cased once, in Python, and bound. The functions are an
    array, so a nested EXISTS over `unnest` compares each. Case-folding means the functions'
    GIN index can't serve this, which is fine: the workspace and part filters come first and a
    part has tens of pins, not thousands.
    """
    wanted = literal(spec.name.value.upper())
    functions = func.unnest(pins.c.functions).alias("f")
    matches_function = (
        select(literal(1))
        .select_from(functions)
        .where(func.upper(functions.column) == wanted)
        .exists()
    )
    return (
        select(literal(1))
        .select_from(pins)
        .where(
            pins.c.workspace_id == part_definitions.c.workspace_id,
            pins.c.part_id == part_definitions.c.id,
            or_(func.upper(pins.c.label) == wanted, matches_function),
        )
        .exists()
    )


# One compiler per filter type, the shape `_BUILDERS` and `_SPEC_KEYS` have. Each takes its
# own type; the values are erased to `Callable[[Spec], ...]` here, and `compile_spec` only
# ever hands a compiler the type it was registered under, so the dispatch stays sound.
_COMPILERS: dict[type, Callable[[Spec], ColumnElement[bool]]] = {
    AllOf: type_cast("Callable[[Spec], ColumnElement[bool]]", _all_of),
    TextContains: type_cast("Callable[[Spec], ColumnElement[bool]]", _text_contains),
    InCategories: type_cast("Callable[[Spec], ColumnElement[bool]]", _in_categories),
    NumberBetween: type_cast("Callable[[Spec], ColumnElement[bool]]", _number_between),
    OneOf: type_cast("Callable[[Spec], ColumnElement[bool]]", _one_of),
    IsBool: type_cast("Callable[[Spec], ColumnElement[bool]]", _is_bool),
    TextAttributeContains: type_cast(
        "Callable[[Spec], ColumnElement[bool]]", _text_attribute_contains
    ),
    HasPin: type_cast("Callable[[Spec], ColumnElement[bool]]", _has_pin),
}


def _containing(text: SearchText) -> str:
    """A search fragment as a bound ILIKE pattern: the wildcards escaped, wrapped in `%`."""
    return f"%{text.value.translate(_LIKE_WILDCARDS)}%"


def _attribute(key: AttributeKey) -> ColumnElement[object]:
    """`attributes -> :k`, the JSONB value under the key, the key a bound parameter.

    `result_type=JSONB` on purpose: the column is a `TypeDecorator` over `AttributeValues`,
    and without it a comparison against the result would try to bind its literal through the
    part's own JSON serializer (a `%pattern%` sent as an attributes map), which fails.
    """
    return part_definitions.c.attributes.op("->", return_type=JSONB)(literal(str(key)))


def _attribute_text(key: AttributeKey) -> ColumnElement[str]:
    """`attributes ->> :k`, the value under the key as text, the key a bound parameter.

    `result_type=Text` for the same reason: this is text now, so an ILIKE pattern binds as a
    string and not as the JSONB the `attributes` column would otherwise infer.
    """
    return part_definitions.c.attributes.op("->>", return_type=Text)(literal(str(key)))


def number_value(key: AttributeKey) -> ColumnElement[Decimal]:
    """`CASE WHEN jsonb_typeof(attributes -> :k) = 'number' THEN (attributes -> :k)::numeric END`.

    NULL for a part whose value is missing or not a number, so a numeric comparison against it
    is NULL — never true — and the part drops out of the filter (requirement 2.7). Public
    because the repository orders by the same expression it filters on: an attribute sort ranks
    parts by this number, with the NULLs (missing and wrong-kind alike) sorting last.
    """
    value = _attribute(key)
    return cast(
        case((func.jsonb_typeof(value) == literal("number"), _attribute_text(key)), else_=None),
        Numeric,
    )


def _contains_pair(key: AttributeKey, value: object) -> ColumnElement[bool]:
    """`attributes @> jsonb_build_object(:k, :v)`: containment the GIN index serves.

    `jsonb_build_object` takes the key and the value as bound parameters and builds the
    one-pair object to test containment against, so neither is ever interpolated.
    """
    pair = cast(func.jsonb_build_object(literal(str(key)), literal(value)), JSONB)
    return part_definitions.c.attributes.op("@>")(pair)


def _decimal(value: Decimal) -> ColumnElement[Decimal]:
    """A bound numeric literal, so a range bound compares as a number and not as text."""
    return cast(literal(str(value)), Numeric)
