# Requirements Document

## Introduction

Parametric search, the last of four specs in `v0.3.0`. The parts list becomes a search:
text across names and part numbers, a category that includes its subcategories, and
filters on the category's typed attributes ("resistors between 1k and 10k in 0805"), on
pins ("parts with an SDA pin"), with sorting and facet counts. It is what the typed
attributes of [ADR 0005](../../../docs/adr/0005-typed-part-attributes.md) and the pinouts of
[ADR 0004](../../../docs/adr/0004-netlist-and-pinouts.md) were built for. The requirements
were written against [design.md](design.md), which came first (Design-First).

The owner decided the scope on 2026-09-25: **search lives inside the catalog pages**. A
global "search everything" palette (`Ctrl K`) stays in the `v0.8.0` roadmap.

Acceptance criteria use EARS: `WHEN <condition> THE SYSTEM SHALL <behaviour>`. Every
criterion acts inside the caller's workspace. This spec's last commit carries
`Release-As: 0.3.0`.

## Glossary

- **The owner**: the single real user. A guest searches their demo bench the same way.
- **Search**: one request for a page of parts: text, category, filters, sort and cursor.
- **Filter**: one condition on one attribute or on the pins: a number range, a set of enum
  options, a boolean, a text fragment, or a pin name.
- **Resolved schema**: a category's own attribute definitions plus its ancestors'.
- **Facets**: for a category, how many parts have each enum option and boolean value, and
  the lowest and highest value of each number attribute.
- **Cursor**: an opaque token that continues a search from where its last page ended.

## Requirements

### Requirement 1: Text and category

**User Story:** As the owner, I want to type part of a name or part number and narrow by
category, so that I find a part without remembering exactly how I named it.

#### Acceptance Criteria

1. WHEN text is searched THE SYSTEM SHALL match parts whose name, manufacturer, part number
   or package contains it, ignoring case.
2. WHEN a category is chosen THE SYSTEM SHALL include the parts of all its subcategories,
   unless asked for that category alone.
3. WHEN text and a category are both given THE SYSTEM SHALL return only parts that match
   both.
4. WHEN nothing is given THE SYSTEM SHALL return every part of the workspace.
5. WHEN searched text contains `%` or `_` THE SYSTEM SHALL match those characters literally.

### Requirement 2: Attribute filters

**User Story:** As the owner, I want to filter a category's parts by their attributes, so
that "resistors between 1k and 10k, ±1 %, 0805" is one search.

#### Acceptance Criteria

1. WHEN a number attribute is filtered with a minimum, a maximum or both THE SYSTEM SHALL
   return parts whose value lies within them, bounds included.
2. WHEN a range bound is typed in engineering notation (`1k`, `4k7`, `100nF`) THE SYSTEM
   SHALL read it as the attribute's own values are read, unit included, and compare exactly.
3. WHEN an enum attribute is filtered with one or more options THE SYSTEM SHALL return parts
   whose value is any of them.
4. WHEN a boolean attribute is filtered with true or false THE SYSTEM SHALL return parts with
   that value.
5. WHEN a text attribute is filtered with a fragment THE SYSTEM SHALL return parts whose
   value contains it, ignoring case.
6. WHEN several filters are given THE SYSTEM SHALL return only parts that satisfy all of
   them.
7. WHEN a part has no value for a filtered attribute, or a value of the wrong kind after a
   schema change THE SYSTEM SHALL leave it out of that filter's matches, and SHALL NOT fail.
8. WHEN an attribute filter is given without a category THE SYSTEM SHALL refuse it with 422,
   because only a category's schema says what the key means.
9. WHEN a filter names a key the category's resolved schema doesn't define, or doesn't fit
   the attribute's kind (a range on an enum), or a range whose minimum is above its maximum
   THE SYSTEM SHALL refuse it with 422 and name the filter.

### Requirement 3: Pin filter

**User Story:** As the owner, I want to find parts by their pins, so that "which of my
sensors speak I²C?" is a search for `SDA`.

#### Acceptance Criteria

1. WHEN a pin name is searched THE SYSTEM SHALL return parts with a pin whose label or one of
   whose alternate functions equals it, ignoring case.
2. WHEN the pin filter is combined with other filters THE SYSTEM SHALL require all of them.

### Requirement 4: Sorting and paging

**User Story:** As the owner, I want to sort results, including by an attribute, so that the
smallest capacitor or the newest part comes first.

#### Acceptance Criteria

1. WHEN a search is sorted THE SYSTEM SHALL sort by newest (the default), name, or a number
   attribute of the chosen category's resolved schema, ascending or descending.
2. WHEN results are sorted by an attribute THE SYSTEM SHALL put parts without a value last,
   in either direction.
3. WHEN a search has more results than one page THE SYSTEM SHALL return a cursor, and the
   cursor SHALL continue the same search in the same order, without repeating or skipping a
   part, even when parts share a sort value.
4. WHEN a cursor is used with a different search THE SYSTEM SHALL refuse it with 422.
5. WHEN a page is asked for THE SYSTEM SHALL return at most 100 parts, 50 by default.

### Requirement 5: Facets

**User Story:** As the owner, I want to see what values a category's parts actually have, so
that I pick a filter that finds something.

#### Acceptance Criteria

1. WHEN the facets of a category are requested THE SYSTEM SHALL return, for its resolved
   schema, each enum option with how many parts have it, each boolean attribute's counts of
   true and false, and each number attribute's lowest and highest value.
2. WHEN facets are requested with text or a pin filter THE SYSTEM SHALL count only the parts
   matching them; the attribute filters SHALL NOT narrow the facets, so every option stays
   selectable.
3. WHEN a number attribute has no values THE SYSTEM SHALL return no range for it rather than
   fail.

### Requirement 6: Web

**User Story:** As the owner, I want a parts page where filters appear for the category I
choose, so that searching needs no syntax.

#### Acceptance Criteria

1. WHEN the parts page is used THE SYSTEM SHALL show a text box, a category picker, a pin box,
   and, once a category is chosen, one filter per attribute of its resolved schema: a
   minimum and maximum for numbers with the normalized value shown as it is typed,
   checkboxes with counts for enum options, a three-way choice for booleans, a text box for
   text.
2. WHEN a filter changes THE SYSTEM SHALL update the results without a submit button, waiting
   for typing to pause.
3. WHEN a category is chosen THE SYSTEM SHALL add a column per number and enum attribute to
   the results, and let those columns and the name be sorted by clicking their headers.
4. WHEN filters are set THE SYSTEM SHALL keep them in the page's address, so a search can be
   bookmarked, shared, and restored with Back and Forward.
5. WHEN the API refuses a filter THE SYSTEM SHALL show the refusal next to that filter.
6. WHEN no part matches THE SYSTEM SHALL say so and offer to clear the filters.
7. WHEN the page is used on a phone THE SYSTEM SHALL fold the filters into a panel that opens
   and closes, and keep the results readable.
8. WHEN any search screen is rendered THE SYSTEM SHALL take every string from an i18n key in
   both `en.json` and `pt-BR.json`, every colour from a theme token, and be usable by
   keyboard.

### Requirement 7: Non-functional

**User Story:** As the owner, I want searches to stay fast as the catalog grows, so that the
small server answers without strain.

#### Acceptance Criteria

1. WHEN text is searched THE SYSTEM SHALL use trigram indexes (`pg_trgm`), not a scan of
   every part's text.
2. WHEN enum and boolean filters are applied THE SYSTEM SHALL use the GIN index on the
   attributes.
3. WHEN a search runs THE SYSTEM SHALL use one query for its page, whatever the number of
   filters.
4. WHEN the database and the domain evaluate the same filters on the same parts THE SYSTEM
   SHALL return the same parts.
5. WHEN migration `0008` is applied THE SYSTEM SHALL be reversible, and the up → down → up
   round trip SHALL pass.
6. WHEN routes or schemas change THE SYSTEM SHALL have `packages/api-client` regenerated.
7. WHEN the test suites run THE SYSTEM SHALL keep API coverage at or above 90 % and web
   coverage at or above 85 %, and every commit SHALL pass `make check` on its own.
