# Design Document: minimum stock

## Overview

Two nullable numbers in catalog, one read that joins them with inventory's counts, and a new
module, `preferences`, that holds what a workspace chose. Answers
[requirements.md](requirements.md).

## Architecture

Catalog owns parts and categories, so it owns the minimums and builds the list. Two things it
needs live elsewhere, and reach it as ports bound in bootstrap, since modules don't import each
other:

- how much there is of each part, from inventory: `PartStock.level(parts, basis)`, over
  `AvailableStock` for free and `PartTotals` for total;
- what the workspace compares against, from preferences: `StockBasisOf`.

`preferences` is a module of its own rather than a column on catalog because the next setting
won't be about stock. It has the usual four layers and one table.

## Components and Interfaces

### catalog

- `PartDefinition.minimum_stock` and `PartDetails.minimum_stock`, so create, edit and a history
  restore carry it. `Category.minimum_stock` and `set_minimum_stock`.
- `CategoryFlags.minimum_stock`: resolved with the flags, the nearest set along the chain.
- `domain/reorder.py`: `minimum_of(part, flags, source)` is the one rule (own, else default;
  0 or not stocked is none); `reorder_lines` filters and orders.
- `ListReorder`: the category tree, `parts.watched(defaulted)` (the parts with their own
  minimum, and the ones with none under a category that has a default), then one stock read.
- `GetPart` and `UpdatePart` answer the resolved `Minimum` on `PartView`.
- `SetCategoryMinimum`, reached through the category patch as the flags are.
- `GET /api/catalog/reorder`.

### preferences

- `WorkspacePreferences(workspace_id, stock_basis)`; no row means the defaults.
- `GetPreferences` writes nothing; `UpdatePreferences` creates the row on the first save.
- `GET` and `PUT /api/preferences`.

### Persistence

Migration `0028`: `minimum_stock integer NULL` with a range CHECK on `part_definitions` and
`categories`; `workspace_preferences(workspace_id PK, stock_basis)` with a CHECK, isolated by
workspace. History's triggers record the two columns as they record the rest.

### Web

- `features/settings`: `SettingsPage`, `usePreferences`, `useUpdatePreferences`. A pick shows
  at once and is saved; saving drops the reorder list.
- `features/catalog`: `ReorderPage`, `ReorderNotice` on the dashboard, `PartMinimum` on the part
  page (it reads the part's stock and the basis, so the page and the list agree),
  `MinimumField` in the part form, `MinimumControl` on the categories page.

## Error Handling

A minimum out of range is a 422 from the request schema, and the domain refuses it too. A
settings save that fails leaves the stored choice shown and says so.

## Testing

Unit tests for the rule, the list and the settings; Postgres tests for the columns, the one
read, the CHECKs and row-level security on the new table; Vitest for each page and field; and
a journey on a guest's bench, since the setting is a workspace's and the other journeys share
one.
