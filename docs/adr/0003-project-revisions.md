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

## Implementation (v0.7)

A revision's firmware line is kept by firmware, as links from each firmware to the revisions it
runs on (13-firmware-versions, [ADR 0006](0006-firmware-snapshots.md)). A link is made and
removed in any status, since what a built board runs keeps changing, and a fork copies its
source's links after the BOM and the netlist.

## Implementation (v0.8)

- **A project goes to the trash with its revisions** (16-soft-delete-and-trash,
  [ADR 0014](0014-soft-delete-and-trash.md)). A revision on its own is still deleted at once. A
  project with a reserved or built revision can't be moved to the trash, just as it couldn't be
  deleted. A BOM in a trashed project still names its parts, so those parts can't be moved to the
  trash either. That way the project always comes back with every line pointing at a real part.
- **The dashboard reads both ends of the lifecycle** (18-dashboard). It lists the parts that
  reserved and built revisions hold, folded per part from the ledger the same way 10 folds them
  per revision. It also lists the drafts whose BOM is short. Each draft is measured by 09's
  shortage report against all the available stock, not a share split between drafts. Drafts of a
  project in the trash are left out.
- **History records a project as one record** with its revisions, BOM lines, designators, nets
  and net pins ([ADR 0015](0015-history-by-triggers.md)). Restoring an earlier version puts back
  the project's name, description and tags only. Revisions that were deleted are never
  re-created from history.

## Consequences

- Old builds stay reproducible, and the dashboard can show what is in each
  build and which parts are tied up in projects.
- One extra level in the UI (project → revision). The latest revision opens by
  default to hide it.
