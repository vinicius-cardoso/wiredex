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

## Consequences

- Queries across projects become possible: every project using GPIO34, or every
  net touching a given part.
- A diagram can be rendered from the data later without migrating anything.
- Entering pinouts takes effort. Reusable part definitions and CSV import of
  pin tables reduce it.
