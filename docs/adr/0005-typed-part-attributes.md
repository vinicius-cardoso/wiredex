# 0005. Typed part categories with JSONB attribute values

- **Status:** Accepted
- **Date:** 2026-09-22

## Context

A resistor has resistance, tolerance and package. An MCU has flash, RAM and a
core. One column per attribute doesn't scale, and free-form key/value pairs
make parametric search useless.

## Decision

- `Category` (a tree: *Passives → Resistors*) defines `AttributeDefinition`s
  with a key, label, type (`number`, `enum`, `text`, `bool`), unit and whether
  it is required. Children inherit the parent's definitions.
- Values are stored in a `JSONB` column on the part definition and **validated in
  the domain** by one validator per type (Strategy).
- Numbers accept engineering notation (`4k7`, `100n`, `2.2µ`) and are
  normalized to SI base units, so `10k` and `10000` compare equal.
- Search uses a GIN index on the JSONB column. Hot numeric attributes get an
  expression index if they need one.

## Implementation (v0.3)

- The `catalog` module holds it: `domain/notation.py` is the only way a number enters
  the domain (`parse_si` reads `4700`, `4.7e3`, `10k`, `4k7` and `100nF`; `format_si`
  prints four significant digits back), `domain/validators.py` has one validator per
  kind, and `domain/schema.py` resolves a category's fields along its ancestor chain.
  A child may not shadow an inherited key, so "which definition applies" has one answer.
- **Exact numbers, end to end.** Values are `Decimal` in SI base units, and the engine
  gets a matching pair in `bootstrap/database.py`: a `json_serializer` that writes a
  `Decimal` as a JSON number, and a `json_deserializer` that reads JSON numbers back
  with `parse_float=Decimal`. JSONB stores numbers as `numeric`, so `10k` and `10000`
  land on the same value with no floating-point drift. Over HTTP the value travels as a
  *string* beside a `display` form, because a JSON number is a double in every client
  we generate and exactness is the point.
- **Flag, don't drop**, the strategy the consequences below asked for:
  - No write ever rewrites a stored value. Changing or removing a definition touches
    the definition row and nothing else.
  - Fit is computed on read. `AttributeSchema.review` lists one problem per offending
    attribute — `missing_required`, `wrong_kind`, `not_in_options`, `unknown_key` — and
    the part is answered with `needs_review: true`, never refused.
  - A removed definition's values stay where they are, as `unknown_key` problems, so
    they are visible and defining the key again with the same kind makes them valid.
  - Editing a part validates the whole attribute map, so a part is never stored
    half-valid and saving clears every problem at once.
- `key` and `kind` can't change on a definition: either change makes it a different
  attribute wearing the same name, and flag-don't-drop would then be flagging data the
  owner never touched. Remove the attribute and define a new one.
- The GIN index on `part_definitions.attributes` is in place from migration 0005, even
  though `parametric-search` is what will query it: building it later means building it
  over a full table.

## Search (v0.3, parametric-search)

The attributes above are what parametric search queries. It is a **specification**: the
domain holds small filter objects (a number range, a set of enum options, a boolean, a text
fragment, a pin name) that each know how to match one part, and the infrastructure compiles
the same objects to one SQL query, one case per filter type. Domain code stays free of
SQLAlchemy; a new filter is a new class plus a new compile case.

- **Validated against the resolved schema.** A filter names an attribute key, and only the
  chosen category's resolved schema (its own definitions plus its ancestors') says whether
  the key exists and what kind it is. The search loads that schema once, turns raw filters
  into typed ones, and parses range bounds with the attribute's unit through `parse_si`, so
  `4k7` means 4700 in a filter exactly as it does on a part. A filter on an unknown key, of
  the wrong kind, or with a minimum above its maximum is refused with 422 that names it; an
  attribute filter without a category is refused too, because without a schema the key has
  no meaning.
- **Guarded numeric comparisons.** Flag-don't-drop means a part can hold text where a number
  is expected after a schema change. Every numeric comparison is guarded by
  `jsonb_typeof(attributes -> :key) = 'number'`, so a wrong-kind value drops out of that
  filter instead of making the whole query fail. The same guard lets a number attribute be a
  sort key, with wrong-kind and missing values sorted last.
- **Facets ignore the attribute filters.** For a category, facets count each enum option,
  each boolean value, and the lowest and highest of each number attribute, over the parts
  matching only the category, the text and the pin filter. The attribute filters do not
  narrow the facets, so every option stays selectable as the owner adds filters, and the
  counts come from one query.

## Consequences

- Filters like "resistors between 1 k and 10 k in 0805" work.
- Changing a category schema needs a strategy for existing values
  (warn and flag parts, never silently drop data).
