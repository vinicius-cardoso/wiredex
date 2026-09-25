# Requirements Document

## Introduction

Part pinouts, the second of four specs in `v0.3.0`. Each part definition gets a structured
pin table, as [ADR 0004](../../../docs/adr/0004-netlist-and-pinouts.md) decided, so the
netlist of `v0.5.0` can point at real pins. The requirements were written against
[design.md](design.md), which came first (Design-First), as in
[catalog-foundation](../catalog-foundation/requirements.md).

Acceptance criteria use EARS: `WHEN <condition> THE SYSTEM SHALL <behaviour>`. Every
criterion acts inside the caller's workspace, as catalog-foundation already guarantees for
parts.

## Glossary

- **The owner**: the single real user. A guest acts the same way inside their demo bench.
- **Pinout**: a part definition's pins, in their saved order.
- **Pin number**: a pin's identity on its part: `1`…`40` on a DIP, `A1`…`H8` on a BGA,
  `EP` for an exposed pad. Unique within a pinout.
- **Pin label**: the name a datasheet gives a pin (`GPIO21`, `SDA`, `GND`). Labels may repeat.
- **Pin type**: `power`, `ground`, `io`, `input` (input-only), `output`, `analog`, `nc`
  (not connected) or `other`.
- **Alternate functions**: the other roles a pin can take (`ADC1_CH6`, `SDA`, `TOUCH9`).
- **Voltage level**: the pin's supply or logic level, in volts.
- **Row**: a pin's 1-based position in the table, as the editor shows it.

## Requirements

### Requirement 1: A part's pinout

**User Story:** As the owner, I want each part definition to carry its pin table, so that
the wiring I enter later points at real pins instead of names I retype.

#### Acceptance Criteria

1. WHEN the pinout of a part is requested THE SYSTEM SHALL return its pins in the order
   they were saved, each with its number, label, type, alternate functions and voltage
   level.
2. WHEN the pinout of a part that has none is requested THE SYSTEM SHALL return an empty
   list, not 404.
3. WHEN a pinout is saved THE SYSTEM SHALL replace the part's whole pinout with the pins
   sent, in one transaction, so a pinout is never stored half-saved.
4. WHEN a pinout is saved with no pins THE SYSTEM SHALL clear the part's pinout.
5. WHEN a pinout is saved THE SYSTEM SHALL mark the part as updated.
6. WHEN a saved pinout is identical to the stored one THE SYSTEM SHALL answer 200 and
   commit nothing.
7. WHEN a part is deleted THE SYSTEM SHALL delete its pinout with it.
8. WHEN a single part is requested THE SYSTEM SHALL include how many pins its pinout has.
9. WHEN the pinout of a part in another workspace, or of a part that doesn't exist, is
   requested or saved THE SYSTEM SHALL answer 404.

### Requirement 2: Pins

**User Story:** As the owner, I want every pin described the way a datasheet describes it,
so that the pin table can answer "which pin is SDA?" and, later, "is 5 V wired to a 3.3 V
pin?".

#### Acceptance Criteria

1. WHEN a pin number is saved THE SYSTEM SHALL trim it and store it upper-cased, so a BGA
   ball `a1` and `A1` are the same pin.
2. WHEN a pin number is empty, longer than 16 characters, or contains anything other than
   letters, digits and `_ . + -` THE SYSTEM SHALL reject the pinout with 422.
3. WHEN two pins of one pinout have the same number THE SYSTEM SHALL reject the pinout
   with 422 and name both rows.
4. WHEN a pin label is saved THE SYSTEM SHALL trim it and keep its case; an empty label or
   one longer than 40 characters SHALL be rejected with 422.
5. WHEN two pins of one pinout have the same label THE SYSTEM SHALL accept it, because a
   part has many `GND` pins.
6. WHEN a pin type is saved THE SYSTEM SHALL accept exactly one of `power`, `ground`, `io`,
   `input`, `output`, `analog`, `nc` and `other`, and reject anything else with 422.
7. WHEN a pin carries alternate functions THE SYSTEM SHALL store them in the order given,
   trimmed, dropping an exact repeat.
8. WHEN an alternate function is empty, longer than 32 characters or contains whitespace,
   or a pin has more than 16 of them THE SYSTEM SHALL reject the pinout with 422.
9. WHEN a voltage level is entered as `3.3`, `3.3V`, `3V3`, `1V8`, `5` or `-12V` THE
   SYSTEM SHALL store its exact value in volts.
10. WHEN a voltage level can't be read, is in another unit, or is beyond ±1000 V THE
    SYSTEM SHALL reject the pinout with 422.
11. WHEN a pin has no voltage level THE SYSTEM SHALL accept it.
12. WHEN a pinout has more than 1024 pins THE SYSTEM SHALL reject it with 422.
13. WHEN a stored voltage level is returned THE SYSTEM SHALL include both its exact value
    and a display form, like attribute numbers (`3.3V`, `1.8V`).

### Requirement 3: Refusals point at the row

**User Story:** As the owner, I want a refused pinout to say which row is wrong, so that
fixing a pasted table of 40 pins doesn't mean hunting for the bad cell.

#### Acceptance Criteria

1. WHEN a pinout is refused THE SYSTEM SHALL answer 422 with a message, the 1-based row of
   the first offending pin and the field it is about (`number`, `label`, `type`,
   `functions`, `voltage`).
2. WHEN the refusal is about two rows, as a duplicate number is THE SYSTEM SHALL name the
   later row and mention the earlier one in the message.
3. WHEN the pinout as a whole is refused, as too many pins is THE SYSTEM SHALL answer
   without a row.

### Requirement 4: Workspace isolation

**User Story:** As the owner, I want pins to be as private as the parts they belong to, so
that lending a demo account stays safe.

#### Acceptance Criteria

1. WHEN the application connects as its non-owner database role THE SYSTEM SHALL have
   row-level security deny reads and writes of another workspace's pins.
2. WHEN a pin is stored THE SYSTEM SHALL have the database refuse it unless its part
   belongs to the same workspace, even if the application passed a wrong workspace.
3. WHEN a guest's demo bench is reset THE SYSTEM SHALL restore the sample pinouts along
   with the sample parts.

### Requirement 5: Web, reading a pinout

**User Story:** As the owner, I want to see a part's pins on its page, so that I can check a
pin without opening the datasheet.

#### Acceptance Criteria

1. WHEN a part page loads THE SYSTEM SHALL show a pinout section with one row per pin:
   number, label, type, alternate functions and voltage.
2. WHEN a part has no pinout THE SYSTEM SHALL say so and offer to add one.
3. WHEN the pinout section is shown THE SYSTEM SHALL let the rows be narrowed by a filter
   that matches number, label or alternate function, so `SDA` finds the pin whose label is
   `SDI`.

### Requirement 6: Web, editing a pinout

**User Story:** As the owner, I want to type or paste a pin table, so that entering a
40-pin board takes a paste, not forty forms.

#### Acceptance Criteria

1. WHEN the pinout is edited THE SYSTEM SHALL show an editable table: one row per pin, with
   rows that can be added, removed and moved up or down.
2. WHEN a table is pasted from a spreadsheet or a datasheet (tab-, semicolon- or
   comma-separated) THE SYSTEM SHALL read it into rows and show them for review before
   anything replaces the table.
3. WHEN the pasted table's first row looks like a header (`Pin`, `Name`, `Type`…) THE
   SYSTEM SHALL skip it.
4. WHEN a pasted row has fewer columns than expected THE SYSTEM SHALL fill the missing
   fields with empty values, not reject the row.
5. WHEN a pasted type is a common spelling (`PWR`, `VCC`, `GND`, `I/O`, `GPIO`, `IN`,
   `OUT`, `AI`, `N/C`) THE SYSTEM SHALL map it to its type; an unknown spelling SHALL be
   marked on the row, not silently changed.
6. WHEN a pasted row has no type and its label is a power or ground name (`VCC`, `3V3`,
   `5V`, `VIN`, `GND`, `VSS`) THE SYSTEM SHALL suggest `power` or `ground`.
7. WHEN pasted alternate functions share a cell THE SYSTEM SHALL split them on `/`, `;`,
   `|`, `,` (when the table isn't comma-separated) and whitespace.
8. WHEN a pasted preview is accepted THE SYSTEM SHALL replace or extend the table, as
   chosen, without saving yet.
9. WHEN the edited pinout is saved and the API refuses it THE SYSTEM SHALL mark the row and
   field the refusal names and keep every edit.
10. WHEN the editor is left with unsaved changes THE SYSTEM SHALL ask before discarding
    them.
11. WHEN any pinout screen is rendered THE SYSTEM SHALL take every string from an i18n key
    present in both `en.json` and `pt-BR.json`, every colour from a theme token, and give
    every cell input an accessible name that includes its row (`Pin 3, label`).

### Requirement 7: Non-functional

**User Story:** As the owner, I want pinouts to stay fast and the codebase to stay
releasable, so that a 40-pin board costs no more to load than a resistor.

#### Acceptance Criteria

1. WHEN a pinout is read THE SYSTEM SHALL use one query, whatever the number of pins.
2. WHEN a pinout is saved THE SYSTEM SHALL write it in a bounded number of statements
   (delete plus one bulk insert), not one per pin.
3. WHEN migration `0006` is applied THE SYSTEM SHALL be reversible, and the up → down → up
   round trip SHALL pass.
4. WHEN routes or schemas change THE SYSTEM SHALL have `packages/api-client` regenerated,
   so CI's contract gate passes.
5. WHEN the test suites run THE SYSTEM SHALL keep API coverage at or above 90 % and web
   coverage at or above 85 %, and every commit SHALL pass `make check` on its own.
