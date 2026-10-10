# Requirements Document

## Introduction

Part kinds: telling mechanical parts (bolts, nuts, threaded rods, inserts) from electronic ones
(resistors, capacitors, ICs). Wiredex was built around electronic parts, so every part has a
pinout section and a package field and can be wired, which reads as noise on a bolt and let a
heat-set insert be treated like a chip. A category now says which kind its parts are, and the
app follows.

It builds on [01-catalog-foundation](../01-catalog-foundation/requirements.md) and
[02-part-pinouts](../02-part-pinouts/requirements.md), on
[09-bill-of-materials](../09-bill-of-materials/requirements.md) and
[11-netlist-editor](../11-netlist-editor/requirements.md). [design.md](design.md) answers these.

Acceptance criteria use EARS: `WHEN <condition> THE SYSTEM SHALL <behaviour>`. Every criterion
acts inside the caller's workspace.

Owner decisions (2026-10-10):

1. **Wiring is only allowed for electronic parts.**
2. **The kind is a category's setting, inherited by its sub-categories**, as *tracked
   individually* and *not stocked* are. Categories that set nothing are electronic, so
   everything that exists stays as it is.
3. **A change that would make a part mechanical while it has a pinout or is wired is refused**,
   naming the parts and what to do. Nothing is hidden and nothing is deleted.
4. A mechanical part has **no pinout section** and **no package field**, the parts list and
   search **filter by kind**, and a mechanical BOM line **needs no designators**.

Decisions taken without the owner, for the owner to review:

5. **A mechanical BOM line may still carry designators.** A line without designators taking a
   quantity already exists (09's decision 7); it becomes what the form offers first for a
   mechanical part. Why not refuse designators: standoffs and mounting holes are labelled
   (`H1–H4`) on real boards, and the wiring rule is enforced where a pin is named, not here.
6. **A package a part already holds stays visible on it once it is mechanical**, to be read and
   cleared; only an empty package field is left out. Why: a field hidden with a value in it is
   the hidden data decision 3 rules out.
7. **Becoming electronic again is never refused.** Nothing a mechanical part may hold is
   forbidden to an electronic one.
8. **Wired counts in every project, one in the trash included.** Why: a project restored from
   the trash would bring the wiring back.

## Glossary

- **Kind**: electronic or mechanical; what a part's category resolves to.
- **Wired**: named by a pin of a net, through a designator of a BOM line.

## Requirements

### Requirement 1: A category's kind

**User Story:** As the owner, I want to say that a category holds mechanical parts, so that the
app stops treating them as electronic.

#### Acceptance Criteria

1. WHEN a category's kind is set to mechanical, to electronic, or cleared THE SYSTEM SHALL store
   it, and a cleared one SHALL take its parent's answer, electronic at the root.
2. WHEN a category or a part is read THE SYSTEM SHALL say the kind it resolves to.
3. WHEN a change would make parts mechanical, by a category's kind, by moving a category under
   another answer, or by filing a part under a mechanical category, AND one of them has a
   pinout or is wired THE SYSTEM SHALL refuse it with 409, naming up to three of them, counting
   the rest, and saying what to do first.
4. WHEN a change makes parts electronic THE SYSTEM SHALL apply it.
5. WHEN a kind is set to what it already is THE SYSTEM SHALL write nothing.

### Requirement 2: Mechanical parts aren't wired and have no pinout

**User Story:** As the owner, I want wiring kept to electronic parts, so that a bolt never ends
up on a net.

#### Acceptance Criteria

1. WHEN a net is given a pin of a mechanical part THE SYSTEM SHALL refuse it with 422, naming
   the part and saying only electronic parts are wired.
2. WHEN a pinout with pins is saved for a mechanical part THE SYSTEM SHALL refuse it with 409.
3. WHEN a mechanical part's page is shown THE SYSTEM SHALL show no pinout section.
4. WHEN a mechanical part's form is shown THE SYSTEM SHALL leave out the package field, unless
   the part already holds a package.

### Requirement 3: Finding parts by kind

**User Story:** As the owner, I want to list only mechanical or only electronic parts, so that
bolts and resistors aren't mixed when I browse.

#### Acceptance Criteria

1. WHEN the parts search, which the parts page lists by, is asked for a kind THE SYSTEM SHALL return only the parts
   whose category resolves to it, and the choice SHALL be part of the page's address.
2. WHEN no kind is asked for THE SYSTEM SHALL return both, as before.

### Requirement 4: A mechanical part on a bill of materials

**User Story:** As the owner, I want to add eight M3 bolts to a BOM without inventing
designators, so that a mechanical line is a part and a count.

#### Acceptance Criteria

1. WHEN a mechanical part is chosen for a BOM line THE SYSTEM SHALL offer the quantity first and
   SHALL not ask for designators.
2. WHEN designators are given for a mechanical line anyway THE SYSTEM SHALL keep them.
