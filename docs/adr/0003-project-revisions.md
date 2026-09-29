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

## Implementation (v0.5)

Shipped by three specs (08 projects and revisions, 09 the BOM, 10 the lifecycle):

- **Projects and revisions (08).** A `projects` module of its own holds them. A project
  always keeps a revision: `A` is created with the project, and the only revision can't be
  deleted. The latest revision is the one created last, and it opens by default. Labels are
  unique per project, ignoring case, and suggested by stepping the latest label's trailing
  number or letters. The status column and its CHECK held all four states from `v0.5.0`'s
  first migration; only drafts were deletable. A fork copies what the revision holds through
  the unit of work's revision contents in one transaction, records `forked_from` and copies
  no attachments. A project's photos and a revision's files are `files` subjects.
- **The BOM (09).** A revision's BOM is two tables in `projects`, its lines and their
  designators, unique per revision as a key. A line names one part definition by a bare id,
  and a part a BOM names can't be deleted. With designators the quantity is their count. Only
  a draft's BOM changes, under the project's lock. The shortage report is computed at every
  read from catalog and inventory through ports and stored nowhere. A fork copies the BOM
  before any other content.
- **The lifecycle (10).** It is a table, `Draft → Reserved → Built → Dismantled`, with cancel
  back to draft and nothing leaving dismantled. What a revision holds is read from the ledger,
  with no table of its own. Reserved and built revisions can't be deleted and dismantled ones
  can, which replaces 08's *only drafts deletable*. Units are reserved and built with a link
  to the revision.

## Consequences

- Old builds stay reproducible, and the dashboard can show what is in each
  build and which parts are tied up in projects.
- One extra level in the UI (project → revision). The latest revision opens by
  default to hide it.
