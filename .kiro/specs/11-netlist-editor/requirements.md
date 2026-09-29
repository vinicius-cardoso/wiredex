# Requirements Document

## Introduction

The netlist editor, the first of two specs in `v0.6.0` Wiring. It delivers the phase's roadmap
line *Netlist editor on top of real pinouts* and builds the other half of
[ADR 0004](../../../docs/adr/0004-netlist-and-pinouts.md): *a revision's netlist is a set of
nets (name, optional wire color); each net connects pin references, which are a BOM designator
plus a pin number (`U1.21 ↔ U2.SDA`)*. It gives each revision of
[08-projects-and-revisions](../08-projects-and-revisions/design.md) the netlist
[ADR 0003](../../../docs/adr/0003-project-revisions.md) puts there, points every pin reference
at a designator of [09-bill-of-materials](../09-bill-of-materials/design.md)'s BOM and a pin
of [02-part-pinouts](../02-part-pinouts/design.md)'s pinout, and fills 08's fork extension
point after 09's BOM, so a fork carries its source's wiring.

[12-wiring-validation](../12-wiring-validation/requirements.md) comes next: it turns what this
spec answers about each pin reference into the phase's rules (unknown pin, pin reused, voltage
mismatch, input-only driven), adds the pin usage view per part, and closes the phase. Until
then this spec checks one thing only, that a pin reference names a real pin when it is written,
and marks the ones that stopped doing so. Requirements-first: [design.md](design.md) answers
these.

Acceptance criteria use EARS: `WHEN <condition> THE SYSTEM SHALL <behaviour>`. Every criterion
acts inside the caller's workspace.

Owner decisions (2026-09-27) that bind every spec and reach this one: one PR per spec with
auto-merge, and the release PR waits for the phase's last spec (12-wiring-validation), which
only the owner merges. This spec carries no `Release-As` footer. A change history waits for
`v0.8.0` (2026-09-26).

Owner decisions (2026-09-29) on this phase:

- `v0.6.0` is two specs: this one, nets between real pins with wire colors, and
  12-wiring-validation, the four rules and the per-part pin usage view.
- A pin reference that stops resolving, because a pinout was replaced, a BOM line's
  designators changed or a line now names another part, doesn't block that edit and isn't
  deleted: the connection is kept, marked unresolved, and shown as a validation error to fix.
  Blocking an edit in another module couples them too tightly, and dropping wiring loses work.
- A part with no pinout is wired by pin number (`R1.1`, `R1.2`); its pins aren't checked, and
  12 warns about it rather than calling it an error. Resistors and capacitors rarely get
  pinouts, and they are on every board.
- Wiring findings never block reserving a revision; 12 shows them as warnings in the reserve
  dialog.

## Glossary

- **The owner**: the single real user. A guest acts the same way inside their demo bench.
- **Netlist**: a revision's nets, what is wired to what on that revision (ADR 0004).
- **Net**: one electrical connection: a name, an optional wire color, notes, and the pins it
  connects.
- **Net name**: what the owner calls a net, as in `SDA`, `3V3` or `SOIL_ADC`.
- **Wire color**: one of ten colors a jumper wire comes in: black, brown, red, orange, yellow,
  green, blue, violet, grey and white, the colors of the resistor code.
- **Pin reference**: a BOM designator, a dot and a pin, as in `U1.21`; it names one pin of the
  part on that designator.
- **Pin list**: pin references typed in one field, as in `U1.21, U2.SDA, R1.2`.
- **Designator**: 09's reference designator (`R1`, `U3`), unique on a revision's BOM.
- **Pinout**: 02's pin table of a part definition; each pin has a number, a label, a type,
  functions and a voltage level. Numbers are unique on a part; labels and functions may repeat.
- **Pin number**: a pin's identity on its part: `21`, `A1`, `EP`.
- **Resolution**: what a pin reference names today, computed when the netlist is read:
  *resolved*, *unchecked*, *unknown designator*, *unknown part* or *unknown pin*.
- **Unresolved**: a pin reference whose resolution is unknown designator, unknown part or
  unknown pin.
- **Draft**: a revision's first status (08); the only status whose content can change (09).
- **Fork**: 08's new draft revision started from an existing one.

## Requirements

### Requirement 1: Nets

**User Story:** As the owner, I want each wire of a revision written down as a named net, so
that the breadboard on my desk and the record of it agree.

#### Acceptance Criteria

1. WHEN a net is added to a revision THE SYSTEM SHALL store it with its name, wire color, notes
   and pins, after the revision's existing nets.
2. WHEN a net's name is given THE SYSTEM SHALL trim it and collapse its whitespace, and refuse
   with 422 on the name a name that is then empty, longer than 32 characters or holds a control
   character.
3. WHEN a net's name is the name of another net of the same revision, compared ignoring case,
   THE SYSTEM SHALL refuse it with 409 on the name, naming the net holding it.
4. WHEN a net's wire color is given THE SYSTEM SHALL accept one of the ten wire colors or none,
   and refuse any other value with 422 on the color.
5. WHEN a net's notes are given THE SYSTEM SHALL trim them and collapse their whitespace, read
   blank notes as none, and refuse notes longer than 500 characters with 422 on the notes.
6. WHEN a net is given no pins THE SYSTEM SHALL refuse it with 422 on the pins.
7. WHEN a net is given more than 256 pins THE SYSTEM SHALL refuse it with 422 on the pins.
8. WHEN a net is added to a revision whose netlist already holds 500 nets THE SYSTEM SHALL refuse
   it with 422.
9. WHEN a net is edited THE SYSTEM SHALL replace its name, color, notes and pins with the edit's,
   its own name not counting against it, and write nothing when they are the ones it already
   holds.
10. WHEN a net is removed THE SYSTEM SHALL delete it together with its pin references.
11. WHEN a revision's netlist is read THE SYSTEM SHALL answer its nets in the order they were
    added, each with its pins in canonical order and as canonical text.
12. WHEN a revision or a net that isn't in the workspace is read, edited or removed, or a net is
    named under a revision it doesn't belong to, THE SYSTEM SHALL answer 404.

### Requirement 2: Pin references and pin lists

**User Story:** As the owner, I want to type `U1.21, U2.SDA` the way a schematic labels a
wire, so that entering a net takes one line.

#### Acceptance Criteria

1. WHEN a pin reference is given THE SYSTEM SHALL read, after Unicode NFKC and trimming, the
   text before the first dot as a designator by 09's rules and the text after it as the pin, and
   refuse with 422 naming it a reference with no dot, an invalid designator or an empty pin.
2. WHEN a pin list is given THE SYSTEM SHALL read items separated by commas or whitespace, each
   item one pin reference.
3. WHEN a pin reference is stored THE SYSTEM SHALL store its designator canonical, as 09 stores
   it, and its pin as the pin number it resolves to, trimmed and upper-cased, so `u1.21` and
   `U1.21` are one reference.
4. WHEN two references of one net name the same pin, typed the same way or not (`U2.3` and
   `U2.SDI`), THE SYSTEM SHALL refuse the net with 422 on the pins naming the second.
5. WHEN a net's pins are written back THE SYSTEM SHALL order them by designator as 09 orders
   designators, then by pin number comparing runs of digits as numbers (`2` before `10`, `A2`
   before `A10`), and join them with a comma and a space: `U1.2, U1.10, U2.3`.
6. WHEN the canonical text of a net's pins is read again THE SYSTEM SHALL read the same pin
   references.
7. WHEN the same pin is in two nets of one revision THE SYSTEM SHALL store both, leaving the
   finding to 12-wiring-validation.

### Requirement 3: New references name real pins

**User Story:** As the owner, I want a net to point only at pins that exist, so that a typo
never slips into the wiring.

#### Acceptance Criteria

1. WHEN a net is written THE SYSTEM SHALL resolve each pin reference it didn't hold before
   against the revision's BOM and the pinout of the part on the reference's designator, as they
   stand in the write's transaction.
2. WHEN a new reference's designator is on no line of the revision's BOM THE SYSTEM SHALL refuse
   the net with 422 on the pins, naming the reference.
3. WHEN a new reference's designator is on a line whose part the workspace's catalog no longer
   holds THE SYSTEM SHALL refuse the net with 422 on the pins, naming the reference.
4. WHEN a new reference names a pin of a part that has a pinout THE SYSTEM SHALL take the pin
   whose number it is, and otherwise the one pin whose label it is, and otherwise the one pin
   one of whose functions it is, comparing labels and functions ignoring case.
5. WHEN a new reference's pin matches no number, label or function of a part that has a pinout
   THE SYSTEM SHALL refuse the net with 422 on the pins, naming the reference.
6. WHEN a new reference's pin matches no number and a label or a function carried by more than
   one pin THE SYSTEM SHALL refuse the net with 422 on the pins, naming the reference and the
   numbers of the pins it could be.
7. WHEN a new reference names a pin of a part with no pinout THE SYSTEM SHALL accept its pin as
   a pin number by 02's rules, refusing with 422 a pin that isn't one, and store it unchecked.
8. WHEN an edited net keeps a reference it already held THE SYSTEM SHALL keep it as stored,
   whatever it resolves to now, so an edit never has to fix a reference it didn't touch.

### Requirement 4: Resolution follows the BOM and the catalog

**User Story:** As the owner, I want my wiring kept when I change a BOM or a pinout, and marked
where it no longer fits, so that I fix it instead of typing it again.

#### Acceptance Criteria

1. WHEN a revision's netlist is read THE SYSTEM SHALL answer, for each pin reference, its
   resolution: *resolved* with the pin's label, type, functions and voltage level when the part
   on its designator has a pinout holding its number; *unchecked* when that part has no pinout;
   *unknown designator* when no BOM line of the revision holds its designator; *unknown part*
   when the line names a part the catalog no longer holds; and *unknown pin* when the part's
   pinout holds no such number.
2. WHEN a reference is answered THE SYSTEM SHALL include its designator's part, by id and name,
   whenever its designator is on the BOM and the catalog holds the part.
3. WHEN a netlist is read THE SYSTEM SHALL compute every resolution from the BOM, the catalog and
   the pinouts as they stand at that read, and store none of it.
4. WHEN a part's pinout is replaced, a BOM line's designators or part change, a BOM line is
   removed, or a part is renamed THE SYSTEM SHALL write that change as it did before this spec,
   leave every net and pin reference as it was, and answer each reference at the next read by
   the rule of 4.1.
5. WHEN a netlist is read THE SYSTEM SHALL answer a summary: its nets, its pin references, and
   how many of those are unchecked and how many unresolved.

### Requirement 5: What a revision's status locks

**User Story:** As the owner, I want a revision's wiring frozen once I reserve or build it, so
that the record of a build stays the build.

#### Acceptance Criteria

1. WHEN a net is added to, edited on or removed from a revision that isn't a draft THE SYSTEM
   SHALL refuse it with 409 and write nothing.
2. WHEN a revision's netlist is read THE SYSTEM SHALL say whether it can be changed, which it can
   only while the revision is a draft.
3. WHEN a net is added, edited or removed THE SYSTEM SHALL update its revision's last change, so
   the project's last activity follows it.
4. WHEN net writes to one project arrive together, or together with BOM writes, changes to its
   revisions or transitions, THE SYSTEM SHALL apply them one at a time, so no two nets of a
   revision share a name, every new reference is checked against the BOM the previous change
   left, and no net is written to a revision that stopped being a draft.
5. WHEN a revision or a project is deleted THE SYSTEM SHALL delete its nets and their pin
   references with it.
6. WHEN a revision is reserved THE SYSTEM SHALL reserve it whatever its netlist holds, resolved
   or not.

### Requirement 6: Forking copies the netlist

**User Story:** As the owner, I want a fork to start with the wiring of the revision it came
from, so that the perfboard begins wired the way the breadboard was.

#### Acceptance Criteria

1. WHEN a revision is forked THE SYSTEM SHALL copy every net of the source into the fork, with
   its name, color, notes and pin references, in the source's order.
2. WHEN a netlist is copied into a fork THE SYSTEM SHALL copy every pin reference as stored,
   resolved or not, give each copied net its own identity, and leave the source's nets
   unchanged.
3. WHEN a revision is forked THE SYSTEM SHALL copy its netlist whatever its status, after its
   BOM, so each copied reference resolves in the fork as it did in the source.
4. WHEN copying a netlist, or any other step of a fork, fails THE SYSTEM SHALL write neither the
   fork nor any copied line or net.

### Requirement 7: What the editor picks from

**User Story:** As the owner, I want the editor to offer the designators on my BOM and the pins
of their parts, so that I pick `GPIO21` instead of looking up that it is pin 21.

#### Acceptance Criteria

1. WHEN a revision's netlist is read THE SYSTEM SHALL answer each designator on its BOM, in
   canonical order, with its part's id and name, or unknown when the catalog no longer holds the
   part.
2. WHEN a revision's netlist is read THE SYSTEM SHALL answer, once for each part on its BOM that
   the catalog holds, whether it has a pinout and its pins in their saved order, each with its
   number, label, type, functions and voltage level.
3. WHEN a revision's netlist is read THE SYSTEM SHALL use a fixed number of queries, whatever the
   number of its nets, pin references, BOM lines and pins, the catalog's reads included.

### Requirement 8: Workspace isolation

**User Story:** As the owner, I want a guest's wiring kept inside their bench, so that lending a
demo account stays safe.

#### Acceptance Criteria

1. WHEN the application connects as its non-owner database role THE SYSTEM SHALL have row-level
   security deny reads and writes of another workspace's nets and pin references.
2. WHEN a net or a pin reference is written THE SYSTEM SHALL have the database refuse it unless
   its revision, and a reference's net, belong to the same workspace.
3. WHEN a net is read or written THE SYSTEM SHALL read the projects and catalog rows it needs in
   one transaction under one workspace setting, so row-level security scopes both.
4. WHEN a revision or a net of another workspace is named by id THE SYSTEM SHALL answer 404, not
   403.
5. WHEN a netlist request carries no valid session THE SYSTEM SHALL answer 401 and touch nothing.
6. WHEN a net write carries no CSRF header THE SYSTEM SHALL answer 403 and touch nothing.

### Requirement 9: The demo workspace

**User Story:** As the owner, I want a guest's sample projects to open wired, so that a demo
shows what a netlist is for without typing one.

#### Acceptance Criteria

1. WHEN a demo workspace's sample catalog is restored THE SYSTEM SHALL give the sample
   *ESP32-DevKitC* the pinout of its two 19-pin headers, its input-only pins typed as inputs.
2. WHEN a demo workspace's sample projects are restored THE SYSTEM SHALL give *Weather station*
   `A` and *Greenhouse controller* `A` nets with wire colors, written through the net use case
   and naming pins by number, by label and by function, with at least one reference to a part
   with no pinout.
3. WHEN the sample *Weather station* `B` is restored THE SYSTEM SHALL have the fork copy `A`'s
   nets and then wire its regulator into them.
4. WHEN the sample *Greenhouse controller* `A` is restored THE SYSTEM SHALL write its nets before
   it is reserved.
5. WHEN a demo reset runs again, or a guest is invited, THE SYSTEM SHALL restore the same sample
   pinouts and netlists.

### Requirement 10: Web

**User Story:** As the owner, I want to wire a revision from the keyboard, with the pins of my
parts offered as I type, so that entering a breadboard takes minutes.

#### Acceptance Criteria

1. WHEN a revision is shown THE SYSTEM SHALL show its wiring in the revision's panel, after its
   bill of materials, as a table of its nets, each with its wire color, name, pins and notes.
2. WHEN a pin reference is shown THE SYSTEM SHALL show it as its canonical text with the pin's
   label when it is resolved, and mark an unchecked or unresolved reference with a text that
   says which, not with color alone.
3. WHEN a draft revision's netlist is shown THE SYSTEM SHALL offer a row for a new net, taking a
   name, a wire color, pins and notes, that Enter submits from any field and that clears and
   puts focus back on its first field once the net is added.
4. WHEN pins are typed THE SYSTEM SHALL suggest the BOM's designators, and after a designator and
   a dot the pins of its part by number and label, and let one be chosen with the arrow keys and
   Enter.
5. WHEN a wire color is shown or chosen THE SYSTEM SHALL show a swatch beside the color's name,
   with the swatch's color from a theme token.
6. WHEN a net is edited in the browser THE SYSTEM SHALL edit it in its own row, save it on Enter
   and restore it on Escape.
7. WHEN a net is removed in the browser THE SYSTEM SHALL ask first, in the net's row.
8. WHEN a net write is refused THE SYSTEM SHALL show the refusal on the field it names, and for
   a pin, name the reference it refused.
9. WHEN a revision that isn't a draft is shown THE SYSTEM SHALL show its netlist without controls
   to change it, and say why.
10. WHEN a BOM line or a transition changes what an open netlist shows THE SYSTEM SHALL refresh
    the netlist in place, without a full reload.
11. WHEN the netlist section is rendered THE SYSTEM SHALL take every string from an i18n key
    present in both `en.json` and `pt-BR.json`, and every colour from a theme token.
12. WHEN the netlist editor is operated by keyboard alone THE SYSTEM SHALL let a net be added,
    edited and removed without a pointer, and expose every control with a role and an
    accessible name.
13. WHEN the netlist section or its editor is shown on a phone-width screen THE SYSTEM SHALL
    keep the page free of horizontal scrolling, a table wider than the screen scrolling inside
    its own box.

### Requirement 11: Non-functional

**User Story:** As the owner, I want the netlist to keep the architecture's lines, so that the
wiring rules and the pin usage view build on it without rework.

#### Acceptance Criteria

1. WHEN the API is linted THE SYSTEM SHALL satisfy the import-linter contracts: `projects`
   imports no other module, and only the composition root binds catalog's part and pinout reads
   to the projects unit of work.
2. WHEN migration `0019` is applied THE SYSTEM SHALL only add tables, their indexes and CHECKs,
   and SHALL pass the up → down → up round trip.
3. WHEN a net is written THE SYSTEM SHALL read the revision, its BOM, its nets and the pinouts
   it checks against in a fixed number of queries whatever their size, and write a net's pin
   references in one statement.
4. WHEN routes or schemas change THE SYSTEM SHALL have `packages/api-client` regenerated, so CI's
   contract gate passes.
5. WHEN the API test suite runs THE SYSTEM SHALL keep total coverage at or above 90 %, and the
   web suite at or above 85 %.
6. WHEN net names, pin references and their lists, canonical order, the resolution of a
   reference, a netlist's invariants and the fork's copy are tested THE SYSTEM SHALL check them
   with Hypothesis.
