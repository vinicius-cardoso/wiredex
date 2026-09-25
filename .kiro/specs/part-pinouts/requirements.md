# Requirements: part pinouts

Written against [design.md](design.md), which came first (Design-First), as in
[catalog-foundation](../catalog-foundation/requirements.md). Acceptance criteria use EARS:
`WHEN <condition> THE SYSTEM SHALL <behaviour>`.

"The owner" is the single real user; a guest acts the same way inside their demo bench.
Every criterion acts inside the caller's workspace, as catalog-foundation §6 already
guarantees for parts.

## 1. A part's pinout

**As the owner, I want each part definition to carry its pin table, so that the wiring I
enter later points at real pins instead of names I retype.**

1.1. WHEN the pinout of a part is requested THE SYSTEM SHALL return its pins in the order
they were saved, each with its number, label, type, alternate functions and voltage level.

1.2. WHEN the pinout of a part that has none is requested THE SYSTEM SHALL return an empty
list, not 404.

1.3. WHEN a pinout is saved THE SYSTEM SHALL replace the part's whole pinout with the pins
sent, in one transaction, so a pinout is never stored half-saved.

1.4. WHEN a pinout is saved with no pins THE SYSTEM SHALL clear the part's pinout.

1.5. WHEN a pinout is saved THE SYSTEM SHALL mark the part as updated.

1.6. WHEN a saved pinout is identical to the stored one THE SYSTEM SHALL answer 200 and
commit nothing.

1.7. WHEN a part is deleted THE SYSTEM SHALL delete its pinout with it.

1.8. WHEN a single part is requested THE SYSTEM SHALL include how many pins its pinout has.

1.9. WHEN the pinout of a part in another workspace, or of a part that doesn't exist, is
requested or saved THE SYSTEM SHALL answer 404.

## 2. Pins

**As the owner, I want every pin described the way a datasheet describes it, so that the
pin table can answer "which pin is SDA?" and, later, "is 5 V wired to a 3.3 V pin?".**

2.1. WHEN a pin number is saved THE SYSTEM SHALL trim it and store it upper-cased, so a
BGA ball `a1` and `A1` are the same pin.

2.2. WHEN a pin number is empty, longer than 16 characters, or contains anything other than
letters, digits and `_ . + -` THE SYSTEM SHALL reject the pinout with 422.

2.3. WHEN two pins of one pinout have the same number THE SYSTEM SHALL reject the pinout
with 422 and name both rows.

2.4. WHEN a pin label is saved THE SYSTEM SHALL trim it and keep its case; an empty label or
one longer than 40 characters SHALL be rejected with 422.

2.5. WHEN two pins of one pinout have the same label THE SYSTEM SHALL accept it, because a
part has many `GND` pins.

2.6. WHEN a pin type is saved THE SYSTEM SHALL accept exactly one of `power`, `ground`,
`io`, `input`, `output`, `analog`, `nc` and `other`, and reject anything else with 422.

2.7. WHEN a pin carries alternate functions (`ADC1_CH6`, `SDA`, `TOUCH9`) THE SYSTEM SHALL
store them in the order given, trimmed, dropping an exact repeat.

2.8. WHEN an alternate function is empty, longer than 32 characters, contains whitespace,
or a pin has more than 16 of them THE SYSTEM SHALL reject the pinout with 422.

2.9. WHEN a voltage level is entered as `3.3`, `3.3V`, `3V3`, `1V8`, `5` or `-12V` THE
SYSTEM SHALL store its exact value in volts.

2.10. WHEN a voltage level can't be read, is in another unit, or is beyond ±1000 V THE
SYSTEM SHALL reject the pinout with 422.

2.11. WHEN a pin has no voltage level THE SYSTEM SHALL accept it.

2.12. WHEN a pinout has more than 1024 pins THE SYSTEM SHALL reject it with 422.

2.13. WHEN a stored voltage level is returned THE SYSTEM SHALL include both its exact value
and a display form, like attribute numbers (`3.3V`, `1.8V`).

## 3. Refusals point at the row

**As the owner, I want a refused pinout to say which row is wrong, so that fixing a pasted
table of 40 pins doesn't mean hunting for the bad cell.**

3.1. WHEN a pinout is refused THE SYSTEM SHALL answer 422 with a message, the 1-based row
of the first offending pin and the field it is about (`number`, `label`, `type`,
`functions`, `voltage`).

3.2. WHEN the refusal is about two rows, as a duplicate number is THE SYSTEM SHALL name the
later row and mention the earlier one in the message.

3.3. WHEN the pinout as a whole is refused, as too many pins is THE SYSTEM SHALL answer
without a row.

## 4. Workspace isolation

**As the owner, I want pins to be as private as the parts they belong to.**

4.1. WHEN the application connects as its non-owner database role THE SYSTEM SHALL have
row-level security deny reads and writes of another workspace's pins.

4.2. WHEN a pin is stored THE SYSTEM SHALL have the database refuse it unless its part
belongs to the same workspace, even if the application passed a wrong workspace.

4.3. WHEN a guest's demo bench is reset THE SYSTEM SHALL restore the sample pinouts along
with the sample parts.

## 5. Web: reading a pinout

**As the owner, I want to see a part's pins on its page, so that I can check a pin without
opening the datasheet.**

5.1. WHEN a part page loads THE SYSTEM SHALL show a pinout section with one row per pin:
number, label, type, alternate functions and voltage.

5.2. WHEN a part has no pinout THE SYSTEM SHALL say so and offer to add one.

5.3. WHEN the pinout section is shown THE SYSTEM SHALL let the rows be narrowed by a filter
that matches number, label or alternate function, so `SDA` finds the pin whose label is
`GPIO21`.

## 6. Web: editing a pinout

**As the owner, I want to type or paste a pin table, so that entering a 40-pin board takes
a paste, not forty forms.**

6.1. WHEN the pinout is edited THE SYSTEM SHALL show an editable table: one row per pin,
with rows that can be added, removed and moved up or down.

6.2. WHEN a table is pasted from a spreadsheet or a datasheet (tab-, semicolon- or
comma-separated) THE SYSTEM SHALL read it into rows and show them for review before
anything replaces the table.

6.3. WHEN the pasted table's first row looks like a header (`Pin`, `Name`, `Type`…) THE
SYSTEM SHALL skip it.

6.4. WHEN a pasted row has fewer columns than expected THE SYSTEM SHALL fill the missing
fields with empty values, not reject the row.

6.5. WHEN a pasted type is a common spelling (`PWR`, `VCC`, `GND`, `I/O`, `GPIO`, `IN`,
`OUT`, `AI`, `N/C`) THE SYSTEM SHALL map it to its type; an unknown spelling SHALL be
marked on the row, not silently changed.

6.6. WHEN a pasted row has no type and its label is a power or ground name (`VCC`, `3V3`,
`5V`, `VIN`, `GND`, `VSS`) THE SYSTEM SHALL suggest `power` or `ground`.

6.7. WHEN pasted alternate functions share a cell THE SYSTEM SHALL split them on `/`, `;`,
`|`, `,` (when the table isn't comma-separated) and whitespace.

6.8. WHEN a pasted preview is accepted THE SYSTEM SHALL replace or extend the table, as
chosen, without saving yet.

6.9. WHEN the edited pinout is saved and the API refuses it THE SYSTEM SHALL mark the row
and field the refusal names and keep every edit.

6.10. WHEN the editor is left with unsaved changes THE SYSTEM SHALL ask before discarding
them.

6.11. WHEN any pinout screen is rendered THE SYSTEM SHALL take every string from an i18n
key present in both `en.json` and `pt-BR.json`, every colour from a theme token, and give
every cell input an accessible name that includes its row (`Pin 3, label`).

## 7. Non-functional

7.1. WHEN a pinout is read THE SYSTEM SHALL use one query, whatever the number of pins.

7.2. WHEN a pinout is saved THE SYSTEM SHALL write it in a bounded number of statements
(delete plus one bulk insert), not one per pin.

7.3. WHEN migration `0006` is applied THE SYSTEM SHALL be reversible, and the up → down →
up round trip SHALL pass.

7.4. WHEN routes or schemas change THE SYSTEM SHALL have `packages/api-client`
regenerated, so CI's contract gate passes.

7.5. WHEN the test suites run THE SYSTEM SHALL keep API coverage at or above 90 % and web
coverage at or above 85 %, and every commit SHALL pass `make check` on its own.
