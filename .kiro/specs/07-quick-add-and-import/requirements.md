# Requirements Document

## Introduction

Quick-add and import, the last of three specs in `v0.4.0` Inventory. It delivers the
roadmap's two remaining Inventory lines: *keyboard-first quick-add and duplicate-part*, and
*CSV import with validated preview*. Quick-add defines a part and puts its first stock away
from one short form that every page can open; duplicate starts that form from a part already
described; import reads a spreadsheet of parts and stock, shows what every row will do
without writing anything, and then imports the whole sheet in one transaction.

It builds on [05-inventory-stock](../05-inventory-stock/requirements.md) and
[06-tracked-units](../06-tracked-units/requirements.md), which both left quick-add and import
to this spec. Stock still enters through the ledger's `RECEIVE`, and a unit-tracked part is
still received as units, through the same receive paths the dialogs use. It also closes a gap
05 left open: its repository can search short codes, but no route or screen uses that search,
so this spec makes codes searchable wherever a location is picked (Requirement 9).
Requirements-first: [design.md](design.md) answers these.

Acceptance criteria use EARS: `WHEN <condition> THE SYSTEM SHALL <behaviour>`. Every criterion
acts inside the caller's workspace.

Owner decisions (2026-09-27) that bind every spec and reach this one: one PR per spec with
auto-merge, and the release PR waits for the phase's last spec — this one — and only the
owner merges it. The "not stocked" category flag for consumables belongs to 09 and 10, not
here.

## Glossary

- **The owner**: the single real user. A guest acts the same way inside their demo bench.
- **Quick-add**: a short form, reachable from every page, that defines one part and can
  receive its first stock, in one transaction.
- **Duplicate**: quick-add started from an existing part and prefilled with its values; saving
  it defines a new part that gets a copy of the source part's pinout.
- **Sheet**: CSV text, comma-, semicolon- or tab-separated, with a header row and one entry in
  each later row.
- **Row number**: a row's number as a spreadsheet shows it. The header is row 1.
- **Fixed column**: `category`, `name`, `manufacturer`, `mpn`, `package`, `location`,
  `quantity`, `serial` or `mac`, spelled in English or Brazilian Portuguese. Any other column
  names an attribute key.
- **Plan**: what each row of a sheet will do. The part half is *defines a new part*, *names an
  existing part* or *same part as an earlier row*; the stock half is *nothing*, *a lot
  receipt* or *units*. Each row also carries the problems found in it.
- **Preview**: planning a sheet against the workspace's current catalog and inventory, writing
  nothing.
- **Digest**: a fingerprint of everything a plan will do. The preview answers it and the
  import has to send it back.
- **Import**: carrying out a clean plan whose digest still matches, in one transaction.
- **Problem**: one thing wrong with a row, or with the sheet as a whole: a row number, a
  column, a code the web translates, and a sentence.
- **Lot-counted / unit-tracked**: whether a part's category resolves "tracked individually"
  (05, 06). A unit-tracked part is received as units, a lot-counted one as a quantity.
- **Short code**: a location's human-readable label, `WX-L-NNNN` (05).
- **Location path**: the names from a root location down to a location, separated by `/`, as
  in `Lab / Cabinet A / Drawer 3`. A category path is the same thing over the category tree.

## Requirements

### Requirement 1: Quick-add a part

**User Story:** As the owner, I want to describe a part and put its first stock away in one
short form, so that a bag from the supplier becomes a stocked part in seconds.

#### Acceptance Criteria

1. WHEN a quick-add names a category and a name, and optionally a manufacturer, part number,
   package and attribute values, THE SYSTEM SHALL define the part, validated against the
   category's resolved schema exactly as saving the part form validates it.
2. WHEN a quick-add also names a location and a quantity for a lot-counted part THE SYSTEM
   SHALL record one `RECEIVE` of that quantity into that location, in the same transaction as
   the part, and answer with the lot's balance.
3. WHEN a quick-add names a location and a quantity for a unit-tracked part THE SYSTEM SHALL
   receive that many units, each with its own `WX-U-…` code and a blank serial and MAC, in the
   same transaction as the part, and answer with the codes.
4. WHEN any part of a quick-add is refused THE SYSTEM SHALL write nothing: neither the part nor
   its stock.
5. WHEN a quick-add's values are refused THE SYSTEM SHALL answer 422 listing every problem at
   once, each naming the field it is about.
6. WHEN a quick-add's manufacturer and part number already belong to a part THE SYSTEM SHALL
   answer 409 and name that part, so the owner can open it instead.
7. WHEN a quick-add gives a quantity without a location, or a location without a quantity,
   THE SYSTEM SHALL refuse it with 422.
8. WHEN a quick-add's quantity is below 1, above 1,000,000 for a lot-counted part, or above
   100 for a unit-tracked part THE SYSTEM SHALL refuse it with 422 on the quantity.
9. WHEN a quick-add names a location that isn't in the workspace THE SYSTEM SHALL refuse it
   with 422 on the location.

### Requirement 2: Keyboard-first, from any page

**User Story:** As the owner, I want quick-add one keystroke away on every page, so that
adding a part never pulls me out of what I was doing.

#### Acceptance Criteria

1. WHEN any page of the signed-in app is shown THE SYSTEM SHALL offer a *Quick add* button in
   the header.
2. WHEN Alt+N is pressed while focus is not in a text field THE SYSTEM SHALL open quick-add.
3. WHEN quick-add opens THE SYSTEM SHALL put focus on its first empty field, let every field be
   reached with Tab, submit with Enter from any field, and close with Escape.
4. WHEN quick-add's location field is typed into THE SYSTEM SHALL suggest the locations whose
   name, path or short code contains the text, and let one be picked with the arrow keys and
   Enter.
5. WHEN a quick-add succeeds THE SYSTEM SHALL say what was added, with any minted unit codes,
   put focus on *Add another*, and offer to open the new part.
6. WHEN *Add another* is chosen THE SYSTEM SHALL keep the category, manufacturer, package and
   location, clear every other field, and put focus on the name.
7. WHEN another part of the app asks quick-add to open, optionally with a part to duplicate, a
   category, a location or a name, THE SYSTEM SHALL open the same dialog prefilled with them.

### Requirement 3: Duplicate a part

**User Story:** As the owner, I want to start a new part from one I already described, so
that the 4k7 next to the 10k takes one changed field, not a whole form.

#### Acceptance Criteria

1. WHEN *Duplicate* is chosen on a part page THE SYSTEM SHALL open quick-add prefilled with the
   part's category, name, manufacturer, package and attribute values, with the part number
   blank and the name selected.
2. WHEN a duplicate is saved THE SYSTEM SHALL define a new part with a copy of the source
   part's pinout, in the same transaction.
3. WHEN a duplicate is saved THE SYSTEM SHALL leave the source part and its pinout unchanged,
   and copy none of its stock, units or attachments.
4. WHEN the part a duplicate copies from isn't in the workspace THE SYSTEM SHALL answer 404 and
   write nothing.

### Requirement 4: Reading a sheet

**User Story:** As the owner, I want to import the spreadsheet I already keep, so that bringing
my bench into Wiredex doesn't mean retyping it.

#### Acceptance Criteria

1. WHEN a sheet is read THE SYSTEM SHALL take its first non-blank row as the header and each
   later non-blank row as one entry, numbered as the spreadsheet numbers it.
2. WHEN a sheet's header row holds a tab THE SYSTEM SHALL read the sheet as tab-separated, else
   as semicolon-separated when the header holds a semicolon, else as comma-separated, with
   quoted cells free to hold the separator, quotes and line breaks.
3. WHEN a header names a fixed column in English or Brazilian Portuguese THE SYSTEM SHALL read
   it as that column, ignoring case, accents and spacing.
4. WHEN a header is not a fixed column THE SYSTEM SHALL read it as an attribute key, and refuse
   the sheet with 422 naming the header when it can't be one.
5. WHEN a column appears twice THE SYSTEM SHALL refuse the sheet with 422 naming it.
6. WHEN a sheet has no header, holds characters that aren't UTF-8, has more than 500 entries or
   more than 64 columns, or is longer than 262,144 characters THE SYSTEM SHALL refuse it with
   422 and say which; a leading byte-order mark is ignored.
7. WHEN a row has a non-blank cell beyond the header's columns THE SYSTEM SHALL report a
   problem on that row, since a cell may hold an unquoted separator; missing trailing cells
   read as blank.
8. WHEN a sheet is written back from what was read THE SYSTEM SHALL produce text that reads as
   the same header and the same cells.
9. WHEN the import template is requested THE SYSTEM SHALL answer a CSV file holding the header
   row of the fixed columns.

### Requirement 5: Rows that define or name a part

**User Story:** As the owner, I want each row to either describe a new part or point at one I
already have, so that one sheet can both fill the catalog and restock it.

#### Acceptance Criteria

1. WHEN a row's manufacturer and part number belong to a part in the workspace THE SYSTEM SHALL
   use that part for the row and ignore the row's other part cells.
2. WHEN a row's manufacturer and part number were first given by an earlier row of the same
   sheet THE SYSTEM SHALL use the part that earlier row defines.
3. WHEN a row names no known part THE SYSTEM SHALL plan a new part from its category, name,
   manufacturer, part number, package and attribute cells, validated as saving the part form
   validates them.
4. WHEN a row's category cell is a path of names separated by `/`, or a single name, THE SYSTEM
   SHALL match it, ignoring case and spacing, against the category whose whole path is those
   names, or else the categories whose path ends with them, and report a problem when none or
   more than one matches.
5. WHEN a new part's cells are checked THE SYSTEM SHALL report every refused cell of the row,
   not only the first, each naming its column.
6. WHEN a row leaves an attribute column blank THE SYSTEM SHALL treat that attribute as not
   given.
7. WHEN a row plans a new part with no category or no name THE SYSTEM SHALL report the missing
   cell.
8. WHEN a row gives no part number THE SYSTEM SHALL plan a new part for it, whatever other rows
   hold.
9. WHEN a row's cell holds a yes-or-no attribute THE SYSTEM SHALL read `true`, `yes`, `sim` or
   `1` as yes and `false`, `no`, `não` or `0` as no, in any case, and report any other text as
   a problem.

### Requirement 6: Rows that put stock away

**User Story:** As the owner, I want a row to say how much sits where, so that the import
restocks lots and receives boards as units.

#### Acceptance Criteria

1. WHEN a row gives a quantity and a location for a lot-counted part THE SYSTEM SHALL plan one
   `RECEIVE` of that quantity into that location.
2. WHEN a row gives a quantity and a location for a unit-tracked part THE SYSTEM SHALL plan that
   many units into that location, each with a blank serial and MAC.
3. WHEN a row gives a serial or a MAC for a unit-tracked part THE SYSTEM SHALL plan one unit
   carrying them, and report a problem when the quantity is anything but blank or 1.
4. WHEN a row gives a serial or a MAC for a lot-counted part THE SYSTEM SHALL report a problem
   saying the part is counted in lots.
5. WHEN a row's location cell is a short code THE SYSTEM SHALL match the location holding it,
   ignoring case, and otherwise match it as a location path the way a category is matched,
   reporting a problem when none or more than one location matches.
6. WHEN a row gives a quantity without a location, or a location without a quantity, THE SYSTEM
   SHALL report the missing cell.
7. WHEN a row gives no quantity, location, serial or MAC THE SYSTEM SHALL plan no stock for it.
8. WHEN a quantity is not a whole number from 1 to 1,000,000 for a lot-counted part, or from 1
   to 100 for a unit-tracked part, THE SYSTEM SHALL report a problem.
9. WHEN a row's serial is already held by a unit of the same part, stored or planned by an
   earlier row, or its MAC by any unit, THE SYSTEM SHALL report a problem saying where it is
   held.
10. WHEN a MAC is given in any spelling 06-tracked-units accepts THE SYSTEM SHALL plan it in its
    canonical form, and report a problem when it isn't six hex octets.
11. WHEN a sheet plans more than 500 units in total THE SYSTEM SHALL report a problem on the
    sheet as a whole.

### Requirement 7: The preview

**User Story:** As the owner, I want to see what an import will do before it does anything, so
that a typo in row 212 is caught before it reaches my stock.

#### Acceptance Criteria

1. WHEN a sheet is previewed THE SYSTEM SHALL plan every row against the workspace's current
   catalog and inventory and write nothing to either.
2. WHEN a sheet is previewed THE SYSTEM SHALL answer each row's number, the part it defines or
   names, the stock it puts away, and every problem found in it.
3. WHEN a sheet is previewed THE SYSTEM SHALL answer a summary: rows read, new parts, existing
   parts, lot receipts and their total quantity, units, and rows with problems.
4. WHEN a sheet is previewed THE SYSTEM SHALL answer the plan's digest, the same for the same
   sheet against the same workspace.
5. WHEN a preview finds problems THE SYSTEM SHALL still answer 200 with the plan, because
   finding them is what a preview is for.
6. WHEN a problem is reported THE SYSTEM SHALL give its row number (none for the sheet as a
   whole), its column, a code the web translates, and a sentence.

### Requirement 8: The import

**User Story:** As the owner, I want a confirmed import to land whole or not at all, so that a
half-imported sheet never leaves me guessing what's in.

#### Acceptance Criteria

1. WHEN a sheet is imported with its preview's digest THE SYSTEM SHALL plan it again and, when
   the plan is clean and its digest matches, define the new parts and record the receipts and
   units, all in one transaction.
2. WHEN an import's plan has any problem THE SYSTEM SHALL answer 422 with the problems and write
   nothing.
3. WHEN an import's plan no longer has the digest sent with it THE SYSTEM SHALL answer 409, say
   the sheet's outcome changed since its preview, and write nothing.
4. WHEN any write of an import fails THE SYSTEM SHALL keep nothing of it: no part, lot,
   movement, balance or unit.
5. WHEN an import succeeds THE SYSTEM SHALL answer the summary, the parts it defined with their
   rows, and the units it received with their codes.
6. WHEN an import records stock THE SYSTEM SHALL record one `RECEIVE` per row, through the
   receive paths the dialogs use, so every lot's `on_hand` equals its ledger sum and, for a
   unit-tracked part, its in-stock units.
7. WHEN a sheet already imported is imported again THE SYSTEM SHALL stock, not define again,
   every part its rows name by part number, and receive the sheet's stock again.

### Requirement 9: Short codes where locations are picked

**User Story:** As the owner, I want to find a bin by its code or its name wherever I pick one,
so that the codes on my drawers are something I can type.

#### Acceptance Criteria

1. WHEN the locations page's filter is typed into THE SYSTEM SHALL show the locations whose
   name or short code contains the text, ignoring case, each with its ancestors so its place in
   the tree stays visible.
2. WHEN a location picker is typed into THE SYSTEM SHALL suggest the locations whose name, path
   or short code contains the text, each shown with its code and path.
3. WHEN a location's exact short code is typed into a location picker THE SYSTEM SHALL pick
   that location on Enter.

### Requirement 10: Workspace isolation

**User Story:** As the owner, I want a guest's quick-adds and imports to stay in their bench,
so that lending a demo account stays safe.

#### Acceptance Criteria

1. WHEN a quick-add or an import runs THE SYSTEM SHALL read and write only the caller's
   workspace, catalog and inventory alike, in one transaction scoped to that workspace, behind
   both of ADR 0007's gates.
2. WHEN a sheet or a quick-add names a category, part, location or unit of another workspace
   THE SYSTEM SHALL treat it as not found.
3. WHEN a quick-add, preview or import request carries no valid session THE SYSTEM SHALL answer
   401 and touch nothing.
4. WHEN a quick-add, preview or import request carries no CSRF header THE SYSTEM SHALL answer
   403 and touch nothing.
5. WHEN a guest's demo workspace is reset THE SYSTEM SHALL clear what quick-add and import
   wrote there like any other change, and restore no sample data of this spec's own.

### Requirement 11: Web

**User Story:** As the owner, I want to preview and import a sheet in the browser, so that
bringing the bench in happens where I already work.

#### Acceptance Criteria

1. WHEN the import page is opened THE SYSTEM SHALL let a sheet be chosen as a file or pasted as
   text, previewed, corrected in place and previewed again.
2. WHEN a preview is shown THE SYSTEM SHALL show the summary and a table of rows with each
   row's part, stock and problems, each problem translated from its code.
3. WHEN a preview has problems, or the text has changed since it was previewed, THE SYSTEM
   SHALL keep *Import* unavailable.
4. WHEN an import answers that the outcome changed THE SYSTEM SHALL say so and offer to preview
   again.
5. WHEN an import succeeds THE SYSTEM SHALL show the summary and the minted unit codes.
6. WHEN the parts page is shown THE SYSTEM SHALL offer *Import from a sheet* beside *New part*.
7. WHEN a quick-add or an import changes the catalog or stock THE SYSTEM SHALL refresh the
   parts, stock and unit views in place, without a full reload.
8. WHEN any quick-add, import or location-finding screen is rendered THE SYSTEM SHALL take every
   string from an i18n key present in both `en.json` and `pt-BR.json`, and every colour from a
   theme token.
9. WHEN those screens are operated by keyboard alone THE SYSTEM SHALL expose every control with
   a role and an accessible name.

### Requirement 12: Non-functional

**User Story:** As the owner, I want intake to keep the architecture's lines and the ledger's
invariants, so that the fastest way in is also a correct one.

#### Acceptance Criteria

1. WHEN a quick-add or an import writes THE SYSTEM SHALL use one unit of work and one
   transaction across catalog and inventory, committed once.
2. WHEN a sheet is planned THE SYSTEM SHALL read the category tree, the location tree and each
   distinct category's schema once, whatever the number of rows.
3. WHEN the API is linted THE SYSTEM SHALL satisfy the import-linter contracts: inventory
   imports neither catalog nor identity, and only the composition root binds catalog into
   inventory's transaction.
4. WHEN this spec is built THE SYSTEM SHALL need no migration, so the head stays `0012`.
5. WHEN routes or schemas change THE SYSTEM SHALL have `packages/api-client` regenerated, so
   CI's contract gate passes.
6. WHEN the API test suite runs THE SYSTEM SHALL keep total coverage at or above 90 %, and the
   web suite at or above 85 %.
7. WHEN the sheet round trip and the preview and import rules are tested THE SYSTEM SHALL check
   them with Hypothesis, under the README's `v0.4.0` property-test gate.
