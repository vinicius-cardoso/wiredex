# Design Document: part kinds

## Overview

A third inherited category flag, `mechanical`, beside `tracked_individually` and `not_stocked`,
and what follows from its resolved answer: no pinout, no wiring, a filter, and a BOM form that
asks for a count. Answers [requirements.md](requirements.md).

## Architecture

The flag lives in catalog and travels as the other two do: resolved along the chain into
`CategoryFlags`, answered to projects through `DescribeParts` as `PartFacts.mechanical`.
Catalog asks projects one new question through bootstrap, "which of these parts are wired",
since only projects knows its nets.

## Components and Interfaces

### catalog

- `Category.mechanical: bool | None`, `set_mechanical`, `CategoryFlags.mechanical`, resolved by
  `resolve_flags_of` as the others are. Migration `0025` adds the nullable column.
- `SetCategoryKind(workspace_id, category_id, mechanical)`, mirroring `SetCategoryStocking`.
- `application/counting.py` becomes `application/turning.py`: the tree arithmetic that finds
  which categories a change turns is the same for any flag, so it takes the flag to read. Two
  guards use it: the existing one for how a part is counted, and `refuse_unfit_mechanical`,
  which refuses while a part turning mechanical has a pinout (`Pinouts.having_pins`, one read)
  or is wired (`PartUses.wired`, answered by projects). Called from `SetCategoryKind`,
  `MoveCategory` and `UpdatePart`. New error `UnfitMechanicalError`, 409.
- `ReplacePinout` refuses a pinout with pins for a part whose category resolves mechanical,
  with the same error. An empty pinout is always accepted: it is how one is removed.
- `PartQuery.mechanical: bool | None` and the search `Spec`'s: the categories of that kind are
  worked out from the tree in memory and the query narrows to `category_id IN (…)`. No index:
  the existing one on `category_id` serves.
- Wire: `CategoryResponse.mechanical` and `mechanical_resolved`, the PATCH body's `mechanical`,
  `PartResponse.mechanical`, and `kind=electronic|mechanical` on the list and the search.

### projects

- `PartFacts.mechanical`, filled by bootstrap from the description's flags.
- `TypedReference.resolve` refuses a designator whose part is mechanical with
  `MechanicalPartError` (422): only a new reference is resolved, so a net is never broken by a
  read.
- `WiredParts(workspace_id, part_ids) -> frozenset[PartId]`: the listed parts a net's pin
  names through a BOM line's designator, in one statement, projects in the trash included.

### bootstrap

- `BomPartUses.wired` over `WiredParts`; `PartFacts.mechanical` in `bootstrap/parts.py` and
  `bootstrap/build.py`.

### Web

- `CategoriesPage`: a third `FlagControl`, *Kind*, with *Inherit*, *Mechanical*, *Electronic*.
  A refusal shows the API's sentence, as the other flags' do.
- `PartPage`: no pinout block for a mechanical part. `PartForm`: no *Package* unless one is
  held.
- Parts list and search: a *Kind* select, kept in the address as `kind`.
- `BomAddRow`: for a mechanical part the quantity field comes first and the designators are
  optional, behind *Add designators*.

## Data Models

`categories.mechanical BOOLEAN NULL`. Additive and nullable: the previous release never selects
it and its inserts leave it null, which reads as inherit, electronic at the root.

## Error Handling

| Case | Answer |
| --- | --- |
| Turning parts mechanical that have a pinout | 409: `X has a pinout: remove it first` |
| Turning parts mechanical that are wired | 409: `X is wired in a project: take it out of the nets first` |
| A pinout for a mechanical part | 409 |
| A net pin naming a mechanical part | 422 |

## Testing Strategy

Domain resolution of the third flag; the three writes refused and let through; the pinout and
net refusals; the wired read against Postgres; the filter in the list and the search; the web's
control, page, form, filter and BOM row; one journey that marks a category mechanical and sees
the app follow.
