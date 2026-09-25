# 0004. Wiring is a structured netlist over structured pinouts

- **Status:** Accepted
- **Date:** 2026-09-22

## Context

Wiring images and Fritzing files can't be searched. The questions that matter
are "what is on GPIO4?", "which pin did I use for SDA?" and "is anything 5 V
wired to a 3.3 V pin?". Answering them needs the data.

## Decision

- A **part definition** owns a `Pinout`: a first-class collection of `Pin`s,
  each with a number, label, type (power, ground, I/O, analog, …), alternate
  functions (`ADC1_CH6`, `SDA`, …) and voltage level.
- A revision's **netlist** is a set of `Net`s (name, optional wire color). Each
  net connects `PinRef`s, which are a BOM designator plus a pin number
  (`U1.21 ↔ U2.SDA`).
- Validation is a list of independent **rules** (Strategy / Open-Closed): the
  pin exists on the part, a pin is in at most one net, the voltage domains
  match, input-only pins are not driven, and more. Each rule returns errors
  and warnings.

## Implementation (v0.3)

The pinout half only; the netlist is still ahead.

- **A pinout is replaced whole, never patched pin by pin.**
  `catalog/application/pinouts.py` has two use cases and no third: `GetPinout` and
  `ReplacePinout`. The editor edits a table and saves that table, so "no two pins
  share a number" is checked in one place, the `Pinout` collection, and a half-saved
  pinout can't exist. A `PUT` carrying no pins clears the table; an identical save
  commits nothing.
- **The number is the pin's identity, so it normalizes hard**: NFKC, trimmed and
  upper-cased, which makes `a1` and `A1` one ball. Labels and functions keep the
  case the datasheet prints them in, because that case is information. Labels repeat
  (a part has several `GND`s); numbers don't.
- `VoltageLevel` is an exact `Decimal` in volts, and reads the silkscreen convention
  (`3V3`, `1V8`, `12V0`) before it falls back to `parse_si`, so `3.3`, `3.3V`, `5`,
  `-12V` and `500mV` all arrive as a value within ±1000 V. It is stored in a
  `numeric` column, so no float rounds 3.3.
- **`pins` is the only catalog table with no imperative mapping.** `SqlPinouts` is
  the mapping: it reads rows into a `Pinout` with Core and writes a `Pinout` back as
  rows, because a pin has no identity outside its pinout and is never loaded alone.
  Rows rather than a JSONB column on the part, because the netlist will join to them
  and `functions` carries a GIN index of its own, for the
  `functions @> ARRAY['SDA']` query that finding parts by function will ask.
- **No surrogate id.** The primary key is `(part_id, number)`, which is exactly how
  the netlist's `PinRef` will reference a pin.
- **The foreign key is on the pair**, `(workspace_id, part_id)` against a new
  `unique (workspace_id, id)` on `part_definitions`, with `ON DELETE CASCADE`.
  Postgres checks foreign keys without row-level security, so a plain `part_id` key
  would let a bug file a pin of one workspace under another workspace's part; with
  the pair the database itself refuses it. That is ADR 0007's third gate. The
  cascade is also what deletes a pinout with its part, so no repository has to
  remember to.
- The cost is fixed whatever the pin count: one `SELECT` reads a pinout, one
  `DELETE` and one bulk `INSERT` replace it, never a statement per pin. A part's
  `pin_count` is a `count(*)`, so a part page says "no pinout yet" without loading
  the pins.
- **Pasted spellings are mapped in the browser, not the domain.** The API accepts
  exactly the eight type names, and `PWR`, `I/O` or `N/C` becomes one of them in
  `pinTypes.ts`, so a guess lands on a row the owner reviews before anything is
  saved. A refused table answers 422 with a structured `{message, row, field}`
  instead of a sentence, which is what lets the editor mark the cell to fix.

## Consequences

- Queries across projects become possible: every project using GPIO34, or every
  net touching a given part.
- A diagram can be rendered from the data later without migrating anything.
- Entering pinouts takes effort. Reusable part definitions and CSV import of
  pin tables reduce it.
