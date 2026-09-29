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
- **No surrogate id.** The primary key is `(part_id, number)`. The netlist's `PinRef`
  names a pin by that number, but through a designator and without a key to this
  table: see v0.6 below.
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

## Implementation (v0.6)

The netlist, then the rules over it.

**The netlist** (11-netlist-editor):

- A revision's netlist is two tables in `projects`, `nets` and `net_pins`, isolated by
  workspace like the BOM.
- **A `PinRef` is a designator and a pin number stored as text**, with no foreign key to
  the BOM or to `pins`. It resolves at every read to one of five states: resolved,
  unchecked (the part has no pinout), unknown designator, unknown part or unknown pin.
- **A reference that stops resolving is kept and marked**, and never blocks the BOM or
  pinout edit that broke it (owner, 2026-09-29). Only a new reference is checked: it must
  name a real pin, matched by number, then by a unique label, then by a unique function,
  and it is stored by number. A part with no pinout is wired by number, unchecked.
- A pin is once per net and may repeat across nets. Nets change only on a draft, under
  the project's lock, and a fork copies the netlist after the BOM.

**The rules** (12-wiring-validation):

- **Each rule is a Strategy class** over `WiringFacts`, the netlist and what each
  reference resolves to, and `RULES` is the tuple of them in reporting order. A rule
  never sees another's findings, so a new rule is one class and one entry.
- Five rules. Errors: an unresolved reference (unknown designator, part or pin), a pin
  reused in two or more nets, a voltage mismatch on a net, and an input-only pin that
  nothing drives. Warning: a part with no pinout that the netlist wires, since its pins
  aren't checked.
- **Findings are computed at every read and stored nowhere**, like the shortage report.
  They never block anything: a revision with errors still reserves, and the reserve
  dialog lists them as warnings.
- **A driver includes an unchecked pin**: a resistor to 3V3 is how a pull-up drives an
  input, and its part has no pinout to say otherwise. Levels compare exactly, so `3V3`
  and `3.30` are one.
- Rules for `nc` pins and for power wired to ground are left for later (owner,
  2026-09-29).
- **Pin usage is one join** from `net_pins` through `bom_designators` and `bom_lines` to
  the part, in every revision of the workspace whatever its status, sorted after the read
  by project, revision and the designator's canonical order. A read is five statements
  whatever the numbers of pins, revisions and nets.

## Consequences

- Queries across projects become possible: every project using GPIO34, or every
  net touching a given part.
- A diagram can be rendered from the data later without migrating anything.
- Entering pinouts takes effort. Reusable part definitions and CSV import of
  pin tables reduce it.
