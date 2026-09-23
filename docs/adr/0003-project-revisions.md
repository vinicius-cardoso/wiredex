# 0003. BOM, wiring and firmware belong to project revisions

- **Status:** Accepted
- **Date:** 2026-09-22

## Context

A project goes from breadboard to perfboard to PCB. If there is only one live
BOM, the record of how v1 was actually built disappears.

## Decision

- `Project` holds identity, description, tags and photos. `Revision` (e.g.
  `A – breadboard`, `B – perfboard`) holds the **BOM**, the **netlist** and the
  **firmware line** it runs.
- A revision has a build lifecycle, implemented as a state machine:

  `Draft → Reserved → Built → Dismantled`, and `Reserved → Draft` on cancel.

  | Transition | Stock effect                                     |
  | ---------- | ------------------------------------------------ |
  | reserve    | `RESERVE` each BOM line (fails listing shortages) |
  | cancel     | `RELEASE` the reservations                        |
  | build      | `CONSUME` the reserved quantities                 |
  | dismantle  | `RETURN` parts to a chosen location               |

- Editing a draft BOM never touches stock. A new revision can be forked from an
  existing one.

## Consequences

- Old builds stay reproducible, and the dashboard can show what is in each
  build and which parts are tied up in projects.
- One extra level in the UI (project → revision). The latest revision opens by
  default to hide it.
