# 0016. Page lists by number, with a total

- **Status:** Proposed
- **Date:** 2026-10-05
- **Supersedes in part:** [0014](0014-soft-delete-and-trash.md) and
  [0015](0015-history-by-triggers.md) (how the list is paged)

## Context

Until `v1.1.0` the long lists were read through opaque cursors: the part search
(`POST /api/catalog/parts/search`), the plain parts list, the trash ([ADR 0014](0014-soft-delete-and-trash.md))
and the activity feed and record timelines ([ADR 0015](0015-history-by-triggers.md)). A cursor
can only ask for the next page, so each list ended in a "Show more" button. The boards list had no
cursor at all and stopped at 200, and Projects and Firmware came whole with no paging.

The redesign wants one bar under every list: numbered pages, a total ("1–50 of 312"), a page
size, and pages that can be bookmarked and walked with Back. A cursor gives none of that.

This record was written without the owner, during the second round of the web redesign, so it
waits for them.

## Decision

- **Every paged endpoint takes `page` and `page_size`, and answers `total`.** `page` runs from 1
  to 100,000 and defaults to 1; `page_size` runs from 1 to 100 and defaults to 50. A value out of
  bounds is a 422 from FastAPI. The answer holds the list's own field (`items`, or `changes` for
  history) with `total`, `page` (the page served) and `page_size`. The shared pieces are
  `shared_kernel/domain/paging.py` (`PageRequest`, `Page`) and `shared_kernel/api/paging.py`
  (the query types and `PagedResponse`).
- **Cursors and `limit` go**, from the part search, the plain parts list, the trash, the feed and
  the timelines, together with their callers in the same change. The plain parts list is
  converted, not removed.
- **The order is each list's existing sort, then the id**, so it is total and a page always holds
  the same rows while nothing changes:

  | List | Order |
  | --- | --- |
  | Part search | the chosen sort, NULLS LAST, then `id` |
  | Plain parts list | `id` |
  | Boards | `created_at DESC, id DESC` |
  | Trash | `trashed_at DESC, id DESC` across the four kinds |
  | Feed and timelines | `id DESC`, the id being its own tie-break |

- **One use case, one unit of work, one count.** Inside it a count statement and the rows are
  built from the same private filter, so they never disagree. The count runs first, then the
  request is clamped to the last page, then OFFSET and LIMIT read the rows.
- **A page past the end answers the last page**, and `page` says which. An empty list answers
  page 1.
- **The trash counts per bin.** It has no table and spans four modules, so each bin returns its
  newest `page × page_size` matches with `count(*) OVER ()` in the same statement. `ListTrash`
  asks the bins one after the other, adds their totals, merges them newest first and slices the
  page. The text filter moves into each module's SQL as ILIKE; a board matches through its part's
  name, which the catalog turns into part ids first. Matching ignores case through `lower()`, as
  ILIKE does.
- **Boards are paged in the API, with no cap.** Nothing bounds how many boards a workspace holds.
  The part filter's choices come from `GET /api/inventory/units/parts`, which names every board's
  part whatever page is shown.
- **Projects and Firmware stay whole in the API** and are paged in the browser with the same bar.
- **On the web, one bar pages every list** (`apps/web/src/shared/ui/pagination.tsx`):
  - Page and size live in the address as `page` and `size`, the defaults left out. Anything
    invalid falls back to the defaults.
  - A page change adds a history entry, so Back walks the pages. A filter or sort change replaces
    the entry, drops `page` and keeps `size`.
  - When the API serves another page than the address asked for, the address is replaced with it.
  - A new size keeps the first row of the current page in view, and a new page scrolls the table
    back to its first row.
  - Its controls are buttons, so the same bar serves the lists and the panels inside a page. A
    record's History and a category's parts keep their page in component state, not the address.
  - A control that can't act is `aria-disabled` and keeps its focus.

## Consequences

- A page can be bookmarked, shared and reached directly, and every list says how much it holds.
- The count reads every matching row, and an offset read costs more the deeper the page. Both
  are fine at one owner's sizes, and the existing indexes still serve the filters.
- A record added or removed between two reads shifts the later pages by one, which the cursor
  didn't. A row can show twice or be missed until the next read. That is accepted.
- The trash reads up to `page × page_size` records per bin, so a deep trash page reads more than
  it shows.
- The trash's text matching now ignores case through `lower()` instead of `casefold()`, so `ß`
  no longer matches `ss`.
- A tab still running the old bundle gets page 1 until it reloads, because the API ignores
  unknown parameters and fields. The footer's version badge already suggests the reload.
- The only consumers, the generated client and this web app, change with the API and ship in one
  release, so the change carries no BREAKING CHANGE footer.
