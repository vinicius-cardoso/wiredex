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

## Consequences

- Filters like "resistors between 1 k and 10 k in 0805" work.
- Changing a category schema needs a strategy for existing values
  (warn and flag parts, never silently drop data).
