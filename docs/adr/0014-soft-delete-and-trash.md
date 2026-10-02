# 0014. Move deleted parts, units, projects and firmware to a trash

- **Status:** Proposed
- **Date:** 2026-10-01

## Context

Until `v0.8.0` every delete was final. One wrong click on a project's Delete button removed its
revisions, BOMs and netlists, and only a database restore could bring them back. Open question 5
of [docs/architecture.md](../architecture.md) asked whether to soft-delete everything and hard
delete only from a trash view.

Soft-deleting every table would reach every read. A revision, a BOM line or a pin that is hidden
but still stored is a second state that every screen has to handle. Every unique index would also
have to decide whether a hidden row still holds its value.

This record was written without the owner, by 16-soft-delete-and-trash, and stays Proposed until
the owner reviews it.

## Decision

- **Four records go to the trash: a part, a unit, a project and a firmware.** These are the
  records with a page and a Delete button, and each one takes its contents along: a part's
  pinout; a project's revisions, BOMs and netlists; a firmware's versions, source files and
  links. Everything else is still deleted at once: revisions, firmware versions, categories,
  locations, attachments, and the rows edited inside a page. History keeps the last state of
  each one ([ADR 0015](0015-history-by-triggers.md)).
- **A `trashed_at` column on the four roots, and none on their contents.** Migration `0022` adds
  `trashed_at timestamptz NULL` to `part_definitions`, `units`, `projects` and `firmware`. It
  also adds a partial index `(workspace_id, trashed_at DESC, id DESC) WHERE trashed_at IS NOT
  NULL`. A revision or a version counts as in the trash when its root is.
- **A record in the trash is absent, exactly like a deleted one.** Each repository's `_mine()`
  select filters `trashed_at IS NULL`. Lists, searches, pickers, counts and other modules' lookups
  leave the record out, and its page answers 404. The locking reads filter too, so a request
  queued behind a move to the trash finds nothing.
- **Moving to the trash refuses whatever deleting refused**: a part a BOM names, a trashed
  project's BOM included; a project with a reserved or built revision; a firmware a flash names;
  a unit that isn't retired. Anything that reaches the trash can therefore be restored whole or
  deleted for good, and deleting for good checks nothing more.
- **Unique values stay held.** No unique index changes. A record in the trash keeps its name,
  MPN, serial and MAC. When a name or MPN is taken by a record in the trash, the refusal says so.
- **A `trash` module lists the trash of all four modules.** It reads newest first, 50 per page by
  default and at most 100, with a cursor on `(trashed_at, id)`. The module declares a `TrashBin`
  port. `bootstrap/trash.py` wraps each module's list, restore, delete-for-good and empty use
  cases in one bin per module. Each bin runs in its module's own unit of work, one bin after the
  other.
- **Nothing leaves the trash on its own.** The owner restores records, deletes them for good, or
  empties the trash. There is no purge timer.
- **What a record needs to come back is kept.** The nightly files prune skips the attachments of
  a record in the trash (`Subjects.kept`). A category can't be deleted while any of its parts is
  in the trash.

## Consequences

- A delete can be undone from `/trash`, contents included. If the release is rolled back, records
  in the trash simply show up again. They never clash with anything, because their unique values
  were held all along.
- While a part is in the trash, its stock lots and units read as an unknown part's, just as they
  did after a delete.
- The trash grows until the owner empties it. One owner's trash stays small, but nothing bounds
  it.
- A read that doesn't go through `_mine()` must filter `trashed_at` itself. 16's design lists the
  reads that do this.
- Open question 5 is settled for these four records only, not for every table.
