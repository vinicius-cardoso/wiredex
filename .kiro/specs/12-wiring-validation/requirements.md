# Requirements Document

## Introduction

Wiring validation, the last of two specs in `v0.6.0` Wiring. It delivers the phase's roadmap
lines *Validation rules (unknown pin, pin reuse, voltage mismatch, input-only driven)* and *Pin
usage view per part ("what's on GPIO4?")*, and closes the phase. It builds
[ADR 0004](../../../docs/adr/0004-netlist-and-pinouts.md)'s last sentence: *validation is a list
of independent rules (Strategy / Open-Closed); each rule returns errors and warnings*, the
Strategy [docs/architecture.md](../../../docs/architecture.md) §5 names for netlist rules.

It stands on [11-netlist-editor](../11-netlist-editor/design.md), which stores nets and their pin
references, refuses a new reference that names no real pin, and answers, for every stored
reference, what it resolves to today: resolved (with the pin's type and voltage level),
unchecked (its part has no pinout), or unresolved (an unknown designator, part or pin). This
spec reads that and nothing new is stored: every finding is computed when the netlist is read,
as 09's shortage report is. Requirements-first: `design.md` and `tasks.md` follow once 11 is on
`main`, so they are written against the code 11 left rather than the code it planned.

Acceptance criteria use EARS: `WHEN <condition> THE SYSTEM SHALL <behaviour>`. Every criterion
acts inside the caller's workspace.

Owner decisions (2026-09-27) that bind every spec and reach this one: one PR per spec with
auto-merge; the release PR waits for the phase's last spec, this one, and only the owner merges
it, which deploys to production. This spec's phase-closing documentation task carries the
`Release-As: 0.6.0` footer. A change history waits for `v0.8.0` (2026-09-26).

Owner decisions (2026-09-29) on this phase:

- `v0.6.0` is two specs: 11-netlist-editor, nets between real pins with wire colors, and this
  one, the rules (unknown pin, pin reused, voltage mismatch, input-only driven) and the per-part
  pin usage view.
- A pin reference that stops resolving is kept in its net, marked unresolved, and shown as a
  validation error to fix; the BOM or pinout edit that caused it is never blocked.
- A part with no pinout is wired by pin number; its references skip the label and voltage
  checks, and it is shown as a warning, *no pinout, pins not checked*, not an error.
- Wiring findings never block reserving a revision: they are shown as warnings in the reserve
  dialog. Reserving is about parts, and a breadboard revision is often wired while it changes.

Owner decisions (2026-09-29) on this spec: *input-only driven* is a net where the only pins
that could supply its signal are input-only pins, so nothing drives it, as requirement 5 reads
it; and a connected `nc` pin and a net joining power to ground stay out of `v0.6.0`.

## Glossary

- **The owner**: the single real user. A guest acts the same way inside their demo bench.
- **Rule**: one independent check over a revision's netlist; it answers findings.
- **Finding**: what a rule reports: its rule, a severity, the nets and pin references it is
  about, and a message code the web translates.
- **Severity**: *error*, something wrong with the wiring or no longer matching the BOM or a
  pinout; or *warning*, something the owner should look at that may be intended.
- **Pin reference**, **resolution**, **resolved**, **unchecked**, **unresolved**: as
  11-netlist-editor defines them.
- **Voltage level**: 02's per-pin level, exact, in volts; a pin may have none.
- **Input-only pin**: a pin whose type is `input` (02); it can be driven but can't drive.
- **Driver**: a pin that can supply a net's signal: a resolved pin of type `output`, `io`,
  `power`, `ground`, `analog` or `other`, or an unchecked reference, whose type isn't known.
- **Pin usage**: for one part, every net of every revision in the workspace that one of its pins
  is on, through a BOM designator holding the part.

## Requirements

### Requirement 1: Rules and findings

**User Story:** As the owner, I want every revision's wiring checked by a set of rules, so that
a mistake shows up on the screen instead of on the bench.

#### Acceptance Criteria

1. WHEN a revision's netlist is read THE SYSTEM SHALL run every rule over it and answer their
   findings with it, each naming its rule, its severity, its message code, and the nets and pin
   references it is about.
2. WHEN a rule runs THE SYSTEM SHALL give it the netlist and the resolution of each reference
   alone, so that no rule depends on another's findings and a rule can be added without changing
   the others.
3. WHEN findings are answered THE SYSTEM SHALL order them errors first, then by rule, then by the
   first net they name in the netlist's order.
4. WHEN a netlist is read THE SYSTEM SHALL compute its findings from the netlist, the BOM, the
   catalog and the pinouts as they stand at that read, and store none of them.
5. WHEN a netlist's summary is answered THE SYSTEM SHALL include how many errors and how many
   warnings its findings hold.
6. WHEN a revision's netlist has no nets THE SYSTEM SHALL answer no findings.

### Requirement 2: Unknown pins, and parts without a pinout

**User Story:** As the owner, I want a reference that no longer matches my BOM or a pinout
called out, so that I fix it instead of trusting a wire to nowhere.

#### Acceptance Criteria

1. WHEN a reference resolves as an unknown designator THE SYSTEM SHALL report an error naming the
   reference and its net, saying the designator is on no line of the BOM.
2. WHEN a reference resolves as an unknown part THE SYSTEM SHALL report an error naming the
   reference and its net, saying the catalog no longer holds the part on its designator.
3. WHEN a reference resolves as an unknown pin THE SYSTEM SHALL report an error naming the
   reference, its net and its part, saying the part's pinout has no such pin.
4. WHEN references resolve unchecked THE SYSTEM SHALL report one warning for each part with no
   pinout, naming the part and its designators that the netlist wires, saying its pins aren't
   checked.
5. WHEN a reference is unresolved or unchecked THE SYSTEM SHALL leave it out of the voltage
   rule, which only reads resolved pins, and in the input-only rule count an unchecked
   reference as a possible driver and an unresolved one as none.

### Requirement 3: A pin in more than one net

**User Story:** As the owner, I want to know when one pin sits in two nets, so that I merge them
or fix the typo that put it there.

#### Acceptance Criteria

1. WHEN the same pin reference is in two or more nets of a revision THE SYSTEM SHALL report one
   error for that reference, naming it and every net holding it.
2. WHEN references are compared for this rule THE SYSTEM SHALL compare them as stored, designator
   and pin number, whatever they resolve to, so an unchecked `R1.1` in two nets is found too.

### Requirement 4: Voltage mismatch

**User Story:** As the owner, I want a 5 V pin wired to a 3.3 V pin caught, so that I don't
learn about it from a dead ESP32.

#### Acceptance Criteria

1. WHEN a net holds two or more resolved pins with a voltage level, and their levels aren't all
   equal, THE SYSTEM SHALL report an error naming the net and, for each level, the references at
   it.
2. WHEN levels are compared THE SYSTEM SHALL compare them exactly, so 3V3 and 3.3 V are one
   level.
3. WHEN a resolved pin has no voltage level THE SYSTEM SHALL leave it out of the comparison.

### Requirement 5: Input-only pins that would have to drive

**User Story:** As the owner, I want to know when a net's only possible source is an input-only
pin, so that I don't plan an output on GPIO34.

#### Acceptance Criteria

1. WHEN a net holds a resolved input-only pin and no driver THE SYSTEM SHALL report an error
   naming the net and its input-only pins, saying nothing on it can drive them.
2. WHEN a net holds an input-only pin and at least one driver THE SYSTEM SHALL report nothing
   for this rule.
3. WHEN a net holds a single reference THE SYSTEM SHALL report nothing for this rule.

### Requirement 6: Findings never block

**User Story:** As the owner, I want to reserve parts for a revision whose wiring I'm still
working out, so that the stock is set aside while I iterate.

#### Acceptance Criteria

1. WHEN a revision whose netlist has errors or warnings is reserved THE SYSTEM SHALL reserve it
   as 10-build-lifecycle does, its findings changing nothing about the reserve.
2. WHEN a net is added or edited in a way that produces a finding THE SYSTEM SHALL store it as
   11 does, and answer the finding at the next read.
3. WHEN a revision's findings are read THE SYSTEM SHALL answer them whatever the revision's
   status, so a reserved or built revision still shows what is wrong with its record.

### Requirement 7: Pin usage per part

**User Story:** As the owner, I want to open a part and see what is wired to each of its pins
across my projects, so that "what's on GPIO4?" takes one look.

#### Acceptance Criteria

1. WHEN a part's pin usage is read THE SYSTEM SHALL answer each of its pins in their saved order,
   with every net of any revision in the workspace that one of its pins is on through a BOM
   designator holding the part: the project, the revision with its status, the designator, and
   the net's name and wire color.
2. WHEN a part's pin usage is read THE SYSTEM SHALL answer, apart from its pins, the references
   to it whose pin number its pinout doesn't hold, and for a part with no pinout every reference
   to it by pin number.
3. WHEN a pin is on no net THE SYSTEM SHALL answer it as free.
4. WHEN a part's pin usage is read THE SYSTEM SHALL order each pin's uses by project name, then
   revision, then designator.
5. WHEN a part's pin usage is read THE SYSTEM SHALL use a fixed number of queries, whatever the
   number of its pins, revisions and nets.
6. WHEN the part isn't in the workspace THE SYSTEM SHALL answer 404.

### Requirement 8: Workspace isolation

**User Story:** As the owner, I want a guest's findings and pin usage drawn from their bench
alone, so that lending a demo account stays safe.

#### Acceptance Criteria

1. WHEN pin usage is read THE SYSTEM SHALL read only the workspace's nets, BOMs, revisions and
   projects, under its workspace setting, so row-level security scopes every row.
2. WHEN a part or revision of another workspace is named by id THE SYSTEM SHALL answer 404, not
   403.
3. WHEN a findings or pin usage request carries no valid session THE SYSTEM SHALL answer 401 and
   touch nothing.

### Requirement 9: The demo workspace

**User Story:** As the owner, I want a guest to see the rules and the pin usage view at work
without breaking anything first, so that a demo shows what wiring checks are for.

#### Acceptance Criteria

1. WHEN a demo bench is restored THE SYSTEM SHALL show its sample netlists with no errors and a
   warning for each sample part without a pinout that they wire.
2. WHEN the sample *ESP32-DevKitC*'s pin usage is read after a restore THE SYSTEM SHALL answer
   GPIO34 on the *Greenhouse controller* `A` net `SOIL`, and GPIO21 on the *Weather station* `A`
   and `B` nets `SDA`.

### Requirement 10: Web

**User Story:** As the owner, I want findings next to the wiring they are about, and a pin usage
table on each part page, so that checking a board is reading one screen.

#### Acceptance Criteria

1. WHEN a revision's netlist is shown THE SYSTEM SHALL show its findings under the nets, errors
   first, each with its message and links to the nets it names, and a message when there are
   none.
2. WHEN a pin reference named by a finding is shown THE SYSTEM SHALL mark its chip with the
   finding's severity, in words and an icon, not color alone.
3. WHEN the netlist's summary is shown THE SYSTEM SHALL show its error and warning counts.
4. WHEN *Reserve parts* is chosen for a revision whose netlist has findings THE SYSTEM SHALL list
   them in the reserve dialog as warnings, and still offer the reserve.
5. WHEN a part with a pinout, or a part some net references, is shown THE SYSTEM SHALL show its
   pin usage: each pin with its label and the nets on it, linking to each revision, and free pins
   as free.
6. WHEN the pin usage table is filtered by text THE SYSTEM SHALL keep the pins whose number,
   label or function contains it, so typing `GPIO4` finds that pin.
7. WHEN a net, a BOM line, a pinout or a transition changes what an open netlist or pin usage
   shows THE SYSTEM SHALL refresh it in place, without a full reload.
8. WHEN a findings or pin usage screen is rendered THE SYSTEM SHALL take every string from an
   i18n key present in both `en.json` and `pt-BR.json`, and every colour from a theme token.
9. WHEN the findings, the reserve dialog's warnings or the pin usage table are operated by
   keyboard alone THE SYSTEM SHALL reach every link and control without a pointer, each with a
   role and an accessible name.
10. WHEN the findings or the pin usage table is shown on a phone-width screen THE SYSTEM SHALL
    keep the page free of horizontal scrolling, a table wider than the screen scrolling inside
    its own box.

### Requirement 11: Non-functional

**User Story:** As the owner, I want the rules to keep the architecture's lines and close the
phase cleanly, so that firmware builds on wiring without rework.

#### Acceptance Criteria

1. WHEN a rule is added THE SYSTEM SHALL need only the new rule and its registration, every
   existing rule unchanged (Strategy, Open/Closed).
2. WHEN the API is linted THE SYSTEM SHALL satisfy the import-linter contracts: `projects`
   imports no other module, and rules live in the domain, importing no framework.
3. WHEN a netlist with its findings is read THE SYSTEM SHALL use the same fixed number of queries
   as 11's netlist read.
4. WHEN routes or schemas change THE SYSTEM SHALL have `packages/api-client` regenerated, so CI's
   contract gate passes.
5. WHEN the API test suite runs THE SYSTEM SHALL keep total coverage at or above 90 %, and the
   web suite at or above 85 %.
6. WHEN each rule, the findings' order and the pin usage are tested THE SYSTEM SHALL check them
   with Hypothesis.
7. WHEN the phase closes THE SYSTEM SHALL have the README's three `v0.6.0` lines ticked, and ADR
   0004, ADR 0001, docs/architecture.md and AGENTS.md recording what the phase built, in one
   commit carrying `Release-As: 0.6.0`.

## Out of scope

- A connected `nc` pin, a net joining a power pin to a ground pin, an unconnected power pin, and
  any other rule not named above: later rules, each a new strategy (requirement 11.1).
- Blocking a reserve or a build on findings (owner, 2026-09-29).
- A rendered wiring diagram (*Later*), and pin usage across workspaces.
