# Requirements Document

## Introduction

The bill of materials, the second of three specs in `v0.5.0` Projects & BOM. It delivers the
phase's roadmap line *BOM editor with designators and a shortage report*, and the README's
Bill of materials row: *designators (`R1–R4`), quantities, notes and a live shortage report
against available stock*. It gives each revision of
[08-projects-and-revisions](../08-projects-and-revisions/design.md) the BOM that
[ADR 0003](../../../docs/adr/0003-project-revisions.md) puts there, builds the `Designator`
value object and the `BillOfMaterials` collection that
[docs/architecture.md](../../../docs/architecture.md) §5 names ("designators unique"), and
fills 08's fork extension point so a fork carries its source's BOM.

It also builds the owner's answer to docs/architecture.md §10 question 3: consumables (solder,
wire, heat-shrink) are marked by a *not stocked* flag on their category, inherited down the
tree as [05-inventory-stock](../05-inventory-stock/design.md)'s *tracked individually* flag
is. Such parts can sit on a BOM, but they are never received, never reserved or consumed, and
never counted short. That touches catalog (the flag), inventory (receipts) and
[07-quick-add-and-import](../07-quick-add-and-import/design.md) (quick-add and import).

[10-build-lifecycle](../10-build-lifecycle/design.md) comes next: it reserves, consumes and
returns what a BOM lists, and closes the phase. Until then nothing reserves stock, so a
part's available stock equals what is on hand. Requirements-first: [design.md](design.md)
answers these.

Acceptance criteria use EARS: `WHEN <condition> THE SYSTEM SHALL <behaviour>`. Every criterion
acts inside the caller's workspace.

Owner decisions (2026-09-27) that bind every spec and reach this one: a BOM line names exactly
one part definition, with no substitutes before 1.0 (docs/architecture.md §10 question 2);
consumables use a "not stocked" category flag, inherited along the category tree like
`tracked_individually`, and this spec builds it; one PR per spec with auto-merge, and the
release PR waits for the phase's last spec (10-build-lifecycle), which only the owner merges.
This spec carries no `Release-As` footer.

## Glossary

- **The owner**: the single real user. A guest acts the same way inside their demo bench.
- **Bill of materials (BOM)**: a revision's list of lines, what it takes to build that
  revision (ADR 0003).
- **BOM line**: one part definition, the designators it fills (possibly none), how many of the
  part, and a note.
- **Designator**: a reference designator: letters, then a number, naming one physical part's
  place on a build: `R1`, `C12`, `U3`, `SW1`.
- **Designator list**: designators and ranges typed in one field, as in `R1–R4, R7`.
- **Range**: two designators of one prefix joined by a dash, `R1–R4`, standing for every
  designator between them.
- **Canonical text**: a designator list as the system writes it back (Requirement 3.7).
- **Quantity**: how many of a line's part the revision needs.
- **Not stocked**: a category flag marking its parts as consumables. It is set to yes or no,
  or left to inherit.
- **Tracked individually**: 05's category flag; a part in such a category is received as
  units, each with a short code (06-tracked-units).
- **Resolved flag**: a category's answer for a flag: the value set on the nearest category
  from it up to the root, and no when none of them sets one. A part's resolved flags are its
  category's.
- **Consumable**: a part whose category resolves not stocked.
- **Need**: the sum of the quantities of a revision's lines that name one part.
- **Available stock**: on hand less reserved, summed over a part's lots. For a unit-tracked
  part that is its in-stock units less the reserved ones. Reserved is zero until
  10-build-lifecycle.
- **Short**: a part's need less its available stock, when that is positive.
- **Shortage report**: for each part on a revision's BOM, its need, available stock, how many
  are short and a status; with a summary.
- **Unknown part**: a part a BOM line names that the workspace's catalog no longer holds.
- **Draft**: a revision's first status (08-projects-and-revisions); the only status whose BOM
  can change.
- **Fork**: 08's new draft revision started from an existing one.

## Requirements

### Requirement 1: The "not stocked" flag

**User Story:** As the owner, I want to mark a whole category of parts as not stocked, so that
solder, wire and heat-shrink can go on a BOM without my counting them.

#### Acceptance Criteria

1. WHEN a category is edited with a not-stocked value of yes, no or inherit THE SYSTEM SHALL
   store that value on the category, and write nothing when it is the value the category
   already holds.
2. WHEN a category's not-stocked flag is resolved THE SYSTEM SHALL answer the value set on the
   nearest category from it up to its root, and no when none of them sets one.
3. WHEN a category's flags are resolved THE SYSTEM SHALL resolve not stocked and tracked
   individually independently of each other, each by the rule of 1.2.
4. WHEN a category is answered THE SYSTEM SHALL include the not-stocked value set on it and its
   resolved not-stocked flag, beside its tracking value and its resolved tracking flag.
5. WHEN a part is answered THE SYSTEM SHALL include its resolved not-stocked and
   tracked-individually flags.
6. WHEN a category's not-stocked flag changes, or a category moves under another, THE SYSTEM
   SHALL leave every stored lot, movement, unit and BOM line as it was.

### Requirement 2: Consumables in inventory, quick-add and import

**User Story:** As the owner, I want a consumable never counted, so that my stock numbers only
cover the parts I actually keep track of.

#### Acceptance Criteria

1. WHEN a part whose category resolves not stocked is received, as a lot or as units, THE
   SYSTEM SHALL refuse it with 422, saying the part isn't stocked, and write nothing.
2. WHEN a part whose category resolves not stocked is recounted at a location where it has no
   lot THE SYSTEM SHALL refuse it with 422 and write nothing.
3. WHEN a part whose category resolves not stocked already holds a lot or units THE SYSTEM
   SHALL recount and move that stock, and move, retire, un-retire and delete those units, as
   it does for any part.
4. WHEN a part resolves both not stocked and tracked individually THE SYSTEM SHALL refuse its
   receipts as not stocked and keep counting the units it already holds as units.
5. WHEN a quick-add or an import row gives stock for a part whose category resolves not stocked
   THE SYSTEM SHALL report the problem `not_stocked` on that stock and plan no stock for it.
6. WHEN a quick-add or an import row defines a part in a not-stocked category and gives no
   stock THE SYSTEM SHALL define the part as it defines any other.

### Requirement 3: Designators

**User Story:** As the owner, I want to type `R1–R4` once instead of four designators, so that
a BOM line reads like the schematic it comes from.

#### Acceptance Criteria

1. WHEN a designator is given THE SYSTEM SHALL accept, after Unicode NFKC and trimming, 1 to 8
   ASCII letters followed by a whole number from 1 to 9999, and refuse anything else with 422
   naming it.
2. WHEN a designator is stored THE SYSTEM SHALL store its letters upper-cased and its number
   without leading zeros, so `r01` and `R1` are one designator.
3. WHEN a designator list is given THE SYSTEM SHALL read items separated by commas or
   whitespace, each item a designator or a range: two designators joined by `-`, `–` or `—`,
   with or without spaces around the dash, the second allowed to be a bare number that takes
   the first one's letters (`R1-4`).
4. WHEN a range is read THE SYSTEM SHALL expand it to every designator from its start to its
   end, and refuse with 422 a range whose end isn't above its start or whose ends have
   different letters.
5. WHEN a designator list names one designator twice, directly or through a range, THE SYSTEM
   SHALL refuse it with 422 naming that designator.
6. WHEN a designator list holds more than 256 designators THE SYSTEM SHALL refuse it with 422.
7. WHEN a designator list is written back THE SYSTEM SHALL order its designators by letters and
   then number, write each run of three or more consecutive numbers as a range with an en dash
   (`R1–R4`), and separate everything else with a comma and a space (`R1, R2, R7`).
8. WHEN the canonical text of a designator list is read again THE SYSTEM SHALL read the same
   designators.

### Requirement 4: BOM lines

**User Story:** As the owner, I want each line of a revision's BOM to say which part, where it
goes and how many, so that the BOM is what I would buy and solder.

#### Acceptance Criteria

1. WHEN a line is added to a revision's BOM THE SYSTEM SHALL store it naming exactly one part
   definition, with its designators, its quantity and its notes, after the revision's existing
   lines.
2. WHEN a line names a part the workspace's catalog doesn't hold THE SYSTEM SHALL refuse it
   with 422 on the part.
3. WHEN a line has designators THE SYSTEM SHALL take their number as its quantity, and refuse
   with 422 on the quantity a quantity given that differs from it.
4. WHEN a line has no designators THE SYSTEM SHALL require a whole-number quantity from 1 to
   10,000, and refuse any other with 422 on the quantity.
5. WHEN a line's notes are given THE SYSTEM SHALL trim them and collapse their whitespace, read
   blank notes as none, and refuse notes longer than 500 characters with 422 on the notes.
6. WHEN a line would hold a designator another line of the same revision holds THE SYSTEM
   SHALL refuse it with 409 on the designators, naming the designator and the line holding it.
7. WHEN a line is added to a revision whose BOM already holds 500 lines THE SYSTEM SHALL refuse
   it with 422.
8. WHEN two lines of one revision name the same part THE SYSTEM SHALL keep both.
9. WHEN a line is edited THE SYSTEM SHALL replace its part, designators, quantity and notes
   with the edit's, its own designators not counting against it, and write nothing when they
   are the ones it already holds.
10. WHEN a line is removed THE SYSTEM SHALL delete it together with its designators.
11. WHEN a revision's BOM is read THE SYSTEM SHALL answer its lines in the order they were
    added, each with its designators both as a list and as canonical text.
12. WHEN a revision or a line that isn't in the workspace is read, edited or removed, or a line
    is named under a revision it doesn't belong to, THE SYSTEM SHALL answer 404.

### Requirement 5: What a revision's status locks

**User Story:** As the owner, I want a revision's BOM frozen once I reserve or build it, so
that the record of a build stays the build.

#### Acceptance Criteria

1. WHEN a line is added to, edited on or removed from a revision that isn't a draft THE SYSTEM
   SHALL refuse it with 409 and write nothing.
2. WHEN a revision's BOM is read THE SYSTEM SHALL say whether it can be changed, which it can
   only while the revision is a draft.
3. WHEN a BOM line is added, edited or removed THE SYSTEM SHALL update its revision's last
   change, so the project's last activity follows it.
4. WHEN BOM writes to one project arrive together, or together with changes to its revisions,
   THE SYSTEM SHALL apply them one at a time, so no two lines of a revision share a designator
   and no line is written to a revision that stopped being a draft.
5. WHEN a revision or a project is deleted THE SYSTEM SHALL delete its BOM lines and their
   designators with it.

### Requirement 6: The shortage report

**User Story:** As the owner, I want every BOM to say what I'm missing, so that I know what to
order before I start building.

#### Acceptance Criteria

1. WHEN a revision's BOM is read THE SYSTEM SHALL answer each part its lines name once, with
   its name, manufacturer, part number, package and resolved flags, the number of lines naming
   it, and its need: the sum of those lines' quantities.
2. WHEN a part on the BOM is stocked THE SYSTEM SHALL answer its available stock, on hand less
   reserved summed over the part's lots, and how many are short: the need less the available
   stock when that is positive, and zero otherwise.
3. WHEN a part on the BOM is tracked individually THE SYSTEM SHALL count as its available stock
   its in-stock units less the reserved ones.
4. WHEN a part on the BOM resolves not stocked THE SYSTEM SHALL answer it as not stocked, with
   no available stock and none short.
5. WHEN a part on the BOM is no longer in the workspace's catalog THE SYSTEM SHALL answer it as
   an unknown part, with no available stock and none short.
6. WHEN a revision's BOM is read THE SYSTEM SHALL answer a summary: its lines, its parts, the
   parts and the pieces short, the not-stocked and the unknown parts, and whether the BOM is
   complete, with no part short and none unknown.
7. WHEN a BOM is read THE SYSTEM SHALL compute its report from the catalog and the stock as
   they stand at that read, and store none of it.
8. WHEN two BOMs differ only in the order of their lines, or in how one part's quantity is
   split across its lines, THE SYSTEM SHALL answer the same need, available stock and shortage
   for every part.

### Requirement 7: Forking copies the BOM

**User Story:** As the owner, I want a fork to start with the BOM of the revision it came from,
so that the perfboard begins with everything the breadboard had.

#### Acceptance Criteria

1. WHEN a revision is forked THE SYSTEM SHALL copy every BOM line of the source into the fork,
   with its part, designators, quantity and notes, in the source's order.
2. WHEN a BOM is copied into a fork THE SYSTEM SHALL give each copied line its own identity,
   put it on the fork, and leave the source's lines unchanged.
3. WHEN a revision is forked THE SYSTEM SHALL copy its BOM whatever its status, and before any
   other revision content registered with the projects module.
4. WHEN copying a BOM, or any later step of a fork, fails THE SYSTEM SHALL write neither the
   fork nor any copied line.

### Requirement 8: Parts that BOMs name

**User Story:** As the owner, I want a part that a BOM names kept in the catalog, so that a
revision never loses track of what it was built from.

#### Acceptance Criteria

1. WHEN a part that a BOM line of the workspace names is deleted THE SYSTEM SHALL refuse it
   with 409, naming the project and revision of up to three of those BOMs and how many more
   there are.
2. WHEN a part that no BOM line names is deleted THE SYSTEM SHALL delete it as it did before
   this spec.
3. WHEN a part a BOM names is renamed or moved to another category, or its category's flags
   change, THE SYSTEM SHALL answer the BOM with the part as it now stands.

### Requirement 9: Workspace isolation

**User Story:** As the owner, I want a guest's BOMs kept inside their bench, so that lending a
demo account stays safe.

#### Acceptance Criteria

1. WHEN the application connects as its non-owner database role THE SYSTEM SHALL have
   row-level security deny reads and writes of another workspace's BOM lines and designators.
2. WHEN a BOM line or a designator is written THE SYSTEM SHALL have the database refuse it
   unless its revision, and a designator's line, belong to the same workspace.
3. WHEN a line names a part of another workspace THE SYSTEM SHALL treat the part as not in the
   catalog.
4. WHEN a revision or a line of another workspace is named by id THE SYSTEM SHALL answer 404,
   not 403.
5. WHEN a BOM request carries no valid session THE SYSTEM SHALL answer 401 and touch nothing.
6. WHEN a BOM write carries no CSRF header THE SYSTEM SHALL answer 403 and touch nothing.

### Requirement 10: The demo workspace

**User Story:** As the owner, I want a guest's sample projects to open with real-looking BOMs,
so that a demo shows what the shortage report is for.

#### Acceptance Criteria

1. WHEN a demo workspace's sample catalog is restored THE SYSTEM SHALL include a not-stocked
   category holding a consumable part.
2. WHEN a demo workspace's sample projects are restored THE SYSTEM SHALL give every sample
   revision BOM lines naming sample parts, among them a part short, a consumable on a line
   without designators and a range of designators, with the forked revision's BOM copied by
   the fork and then extended.
3. WHEN a demo reset runs again, or a guest is invited, THE SYSTEM SHALL restore the same
   sample BOMs.

### Requirement 11: Web

**User Story:** As the owner, I want to write a BOM from the keyboard and see its shortages as I
go, so that planning a build takes minutes, not an evening with a spreadsheet.

#### Acceptance Criteria

1. WHEN a revision is shown THE SYSTEM SHALL show its bill of materials in the revision's
   panel, as a table of its lines, each with its designators, part, quantity, notes and its
   part's stock status.
2. WHEN a draft revision's BOM is shown THE SYSTEM SHALL offer a row for a new line, taking
   designators, a part, a quantity and notes, that Enter submits from any field and that
   clears and puts focus back on its first field once the line is added.
3. WHEN designators are typed THE SYSTEM SHALL preview their canonical text and their count,
   and show that count as the quantity, not editable while designators are given.
4. WHEN a part is being picked THE SYSTEM SHALL suggest the parts whose name, manufacturer or
   part number contains the typed text, and let one be chosen with the arrow keys and Enter.
5. WHEN a line is edited in the browser THE SYSTEM SHALL edit it in its own row, save it on
   Enter and restore it on Escape.
6. WHEN a line is removed in the browser THE SYSTEM SHALL ask first, in the line's row.
7. WHEN a line write is refused THE SYSTEM SHALL show the refusal on the field it names.
8. WHEN a BOM is shown THE SYSTEM SHALL show its shortage report: the summary, each part short
   with its need, available stock and shortage, each unknown part, a link from each of them to
   the part's page, and a message when nothing is short.
9. WHEN a revision that isn't a draft is shown THE SYSTEM SHALL show its BOM without controls
   to change it, and say why.
10. WHEN a category is selected on the categories page THE SYSTEM SHALL offer its not-stocked
    flag as inherit, yes or no, and show the inherited answer while it inherits.
11. WHEN a not-stocked part's page is shown THE SYSTEM SHALL say the part isn't stocked, offer
    no receipt, and offer recount and move only while it holds stock.
12. WHEN quick-add's category resolves not stocked THE SYSTEM SHALL hide the stock fields and
    say why.
13. WHEN deleting a part is refused because BOMs name it THE SYSTEM SHALL show which BOMs.
14. WHEN a BOM line, a quick-add or an import changes what an open BOM shows THE SYSTEM SHALL
    refresh the BOM and its report in place, without a full reload.
15. WHEN any BOM, category or stock screen is rendered THE SYSTEM SHALL take every string from
    an i18n key present in both `en.json` and `pt-BR.json`, and every colour from a theme
    token.
16. WHEN the BOM editor is operated by keyboard alone THE SYSTEM SHALL let a line be added,
    edited and removed without a pointer, and expose every control with a role and an
    accessible name.
17. WHEN the BOM section, its editor or its shortage report is shown on a phone-width screen
    THE SYSTEM SHALL keep the page free of horizontal scrolling, a table wider than the screen
    scrolling inside its own box.

### Requirement 12: Non-functional

**User Story:** As the owner, I want the BOM to keep the architecture's lines, so that the build
lifecycle and the netlist editor build on it without rework.

#### Acceptance Criteria

1. WHEN the API is linted THE SYSTEM SHALL satisfy the import-linter contracts: `projects`
   imports no other module, and only the composition root answers its questions about parts
   and stock and catalog's question of whether a BOM names a part.
2. WHEN migrations `0016` and `0017` are applied THE SYSTEM SHALL only add a column, a unique
   constraint and tables, and each SHALL pass the up → down → up round trip.
3. WHEN a BOM is read THE SYSTEM SHALL use a fixed number of queries, whatever the number of
   its lines and parts, the catalog's and inventory's included.
4. WHEN routes or schemas change THE SYSTEM SHALL have `packages/api-client` regenerated, so
   CI's contract gate passes.
5. WHEN the API test suite runs THE SYSTEM SHALL keep total coverage at or above 90 %, and the
   web suite at or above 85 %.
6. WHEN the flags' resolution, designators and their lists, line quantities, a BOM's
   invariants, the shortage report and the fork's copy are tested THE SYSTEM SHALL check them
   with Hypothesis.
