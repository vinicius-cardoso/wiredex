# Requirements: catalog foundation

Written against [design.md](design.md), which came first (Design-First). Acceptance
criteria use EARS: `WHEN <condition> THE SYSTEM SHALL <behaviour>`.

"The owner" is the single real user. "A guest" is a demo account. Both act inside exactly
one workspace, so the criteria say "the workspace" rather than naming a user.

## 1. Category tree

**As the owner, I want a tree of part categories, so that a resistor and a microcontroller
can be described by different fields without one giant form.**

1.1. WHEN a category is created with a name and no parent THE SYSTEM SHALL store it as a
root category of the current workspace and answer with its id.

1.2. WHEN a category is created with a parent THE SYSTEM SHALL store it as that parent's
child.

1.3. WHEN a category is created with a name that a sibling already uses THE SYSTEM SHALL
reject it with 409 and leave the tree unchanged, including when both are root categories.

1.4. WHEN a category is created more than 6 levels deep THE SYSTEM SHALL reject it with
422 and name the limit.

1.5. WHEN a category is moved under one of its own descendants, or under itself, THE
SYSTEM SHALL reject it with 422 and leave the tree unchanged.

1.6. WHEN a category is moved so that any of its descendants would sit deeper than 6
levels THE SYSTEM SHALL reject it with 422.

1.7. WHEN a category is renamed to a name a sibling already uses THE SYSTEM SHALL reject
it with 409.

1.8. WHEN a category is renamed to its current name THE SYSTEM SHALL answer 200 and
commit nothing.

1.9. WHEN a category that has children or parts is deleted THE SYSTEM SHALL reject it with
409, say which of the two blocks it, and delete nothing.

1.10. WHEN a category with no children and no parts is deleted THE SYSTEM SHALL delete it
and its own attribute definitions.

1.11. WHEN the category tree is requested THE SYSTEM SHALL return every category of the
workspace with its parent, its child count and the number of parts classified directly
under it.

## 2. Attribute schemas

**As the owner, I want each category to declare the fields its parts have, so that every
resistor records resistance and tolerance and nothing records a field that makes no sense
for it.**

2.1. WHEN an attribute is defined on a category with a key, a label, a kind of `number`,
`enum`, `text` or `bool`, and a required flag THE SYSTEM SHALL store it and answer with
its id.

2.2. WHEN an attribute of kind `number` is defined THE SYSTEM SHALL accept an optional
unit symbol and store it as typed.

2.3. WHEN an attribute of kind `enum` is defined with an empty option list THE SYSTEM
SHALL reject it with 422.

2.4. WHEN an attribute is defined with a key that is not a lower-case slug THE SYSTEM
SHALL reject it with 422.

2.5. WHEN an attribute is defined with a key that the category already defines THE SYSTEM
SHALL reject it with 409.

2.6. WHEN an attribute is defined with a key that any ancestor of the category already
defines THE SYSTEM SHALL reject it with 409, because inherited keys may not be shadowed.

2.7. WHEN a category's schema is requested THE SYSTEM SHALL return the category's own
definitions and every definition inherited from its ancestors, each marked with the
category it comes from, ordered by ancestor depth and then by position.

2.8. WHEN an attribute's label, required flag, options or position is changed THE SYSTEM
SHALL store the change without touching any stored part value.

2.9. WHEN a change to an attribute's key or kind is requested THE SYSTEM SHALL reject it
with 422 and say to remove the attribute and define a new one.

2.10. WHEN an attribute is removed THE SYSTEM SHALL delete the definition, keep every
value already stored under its key, and report affected parts as needing review.

## 3. Engineering notation

**As the owner, I want to type `4k7` and `100n` the way they are printed on the part, so
that entering stock isn't an exercise in counting zeros.**

3.1. WHEN a number is entered as plain decimal or scientific notation (`4700`, `4.7e3`)
THE SYSTEM SHALL store its SI value.

3.2. WHEN a number is entered with an SI prefix as a suffix (`10k`, `100n`, `2.2µ`) THE
SYSTEM SHALL store the value the prefix scales to.

3.3. WHEN a number is entered with the prefix standing in for the decimal point (`4k7`,
`2u2`, `1R5`) THE SYSTEM SHALL store 4700, 0.0000022 and 1.5.

3.4. WHEN two spellings of the same magnitude are stored (`10k` and `10000`) THE SYSTEM
SHALL store identical values, exactly, with no floating-point drift.

3.5. WHEN a number carries a trailing unit that matches the attribute's unit (`100nF` on a
farad attribute) THE SYSTEM SHALL accept it and ignore the unit.

3.6. WHEN a number carries a trailing unit that does not match the attribute's unit
(`100nH` on a farad attribute) THE SYSTEM SHALL reject it with 422.

3.7. WHEN `K` is used as a prefix THE SYSTEM SHALL reject it, because `k` is kilo and `K`
is kelvin.

3.8. WHEN a number cannot be read at all THE SYSTEM SHALL reject it with 422, name the
attribute and show an example of an accepted spelling.

3.9. WHEN a stored number is returned THE SYSTEM SHALL include both its exact SI value and
a display form in engineering notation, at most four significant digits.

3.10. WHEN a negative number is entered THE SYSTEM SHALL accept it.

## 4. Part definitions

**As the owner, I want to describe a kind of part once, so that stock, BOMs and wiring can
all point at the same definition later.**

4.1. WHEN a part is defined with a category, a name and attribute values THE SYSTEM SHALL
validate every value against the category's resolved schema before storing anything.

4.2. WHEN a required attribute is missing THE SYSTEM SHALL reject the part with 422 and
name the attribute.

4.3. WHEN a value is sent for a key the schema doesn't define THE SYSTEM SHALL reject the
part with 422 and name the key.

4.4. WHEN an `enum` value is not one of the definition's options THE SYSTEM SHALL reject
the part with 422 and list the options.

4.5. WHEN a `bool` attribute receives the string `"true"` THE SYSTEM SHALL reject it with
422, because the client sends JSON.

4.6. WHEN a part is defined with a manufacturer and an MPN that another part in the
workspace already uses, ignoring case THE SYSTEM SHALL reject it with 409.

4.7. WHEN parts are defined without an MPN THE SYSTEM SHALL allow any number of them.

4.8. WHEN a part is updated THE SYSTEM SHALL replace its whole attribute map and validate
it as a whole, so a part can never be stored half-valid.

4.9. WHEN an update changes nothing THE SYSTEM SHALL answer 200 and commit nothing.

4.10. WHEN a part is moved to another category THE SYSTEM SHALL validate its attributes
against the new category's schema and reject the move if they don't fit.

4.11. WHEN the part list is requested THE SYSTEM SHALL return a page of parts of the
current workspace, filtered by a name substring and by category when asked, with a cursor
for the next page.

4.12. WHEN a part is deleted THE SYSTEM SHALL delete it.

## 5. Schema changes never lose data

**As the owner, I want to fix a category's fields after I've already entered parts, so
that a schema I got wrong early doesn't cost me the data I typed.**

5.1. WHEN a schema change makes stored values no longer fit THE SYSTEM SHALL keep every
stored value untouched.

5.2. WHEN a part whose values no longer fit its schema is read THE SYSTEM SHALL return it
successfully, marked as needing review, with one problem per offending attribute.

5.3. WHEN a part needs review THE SYSTEM SHALL report each problem as one of: a required
value is missing, the value is the wrong kind, the value is not among the options, or the
key is no longer defined.

5.4. WHEN an attribute is defined as required on a category that already has parts THE
SYSTEM SHALL leave those parts readable and report them as needing review.

5.5. WHEN a removed attribute's key is defined again with the same kind THE SYSTEM SHALL
show the previously stored values as valid again.

5.6. WHEN a part that needs review is updated THE SYSTEM SHALL require the whole attribute
map to be valid, so saving clears every problem at once.

## 6. Workspace isolation

**As the owner, I want a guest's bench to be invisible to mine, so that lending someone a
demo account is not a risk.**

6.1. WHEN any catalog request is made THE SYSTEM SHALL resolve the caller's workspace from
their session and act only inside it.

6.2. WHEN a request carries no valid session THE SYSTEM SHALL answer 401 and touch no
catalog data.

6.3. WHEN an authenticated user has no membership THE SYSTEM SHALL answer 401 rather than
fail, because an account with no workspace can't act.

6.4. WHEN a category, attribute or part of another workspace is requested by id THE SYSTEM
SHALL answer 404, not 403, so ids in other workspaces stay unguessable.

6.5. WHEN the application connects as its non-owner database role THE SYSTEM SHALL have
row-level security deny reads and writes of another workspace's catalog rows, even for a
query that forgot its filter.

6.6. WHEN a guest's demo workspace is reset THE SYSTEM SHALL restore its sample
categories, attribute definitions and parts.

## 7. Web

**As the owner, I want to add and find parts in a browser, so that the catalog is usable
from the bench, not only from curl.**

7.1. WHEN the parts page loads THE SYSTEM SHALL list the workspace's parts with their
category, and let the list be narrowed by a search box and a category filter.

7.2. WHEN a category is picked in the part form THE SYSTEM SHALL fetch that category's
resolved schema and render one field per attribute, matched to its kind: a text input with
the unit for `number`, a select for `enum`, a text input for `text`, a switch for `bool`.

7.3. WHEN a number is typed into an attribute field THE SYSTEM SHALL show the normalized
value beside the field as it is typed, and SHALL NOT rewrite what was typed.

7.4. WHEN a required field is left empty THE SYSTEM SHALL block submission and mark the
field, before any request is sent.

7.5. WHEN the API rejects a value THE SYSTEM SHALL show the message on the field it names.

7.6. WHEN a part that needs review is opened THE SYSTEM SHALL show a banner listing its
problems and mark the fields to fix.

7.7. WHEN the categories page is used THE SYSTEM SHALL let a category be added, renamed,
moved and deleted, and show each category's own and inherited attributes.

7.8. WHEN a category can't be deleted because it is in use THE SYSTEM SHALL say so
without leaving the page.

7.9. WHEN any catalog screen is rendered THE SYSTEM SHALL take every string from an i18n
key present in both `en.json` and `pt-BR.json`, and every colour from a theme token.

7.10. WHEN a catalog screen is operated by keyboard alone THE SYSTEM SHALL expose every
control with a role and an accessible name, including the tree.

## 8. Non-functional

8.1. WHEN a category's schema is resolved THE SYSTEM SHALL read the ancestor chain in a
single database round trip.

8.2. WHEN the part list is requested THE SYSTEM SHALL answer without loading attribute
schemas for every row.

8.3. WHEN migration `0005` is applied THE SYSTEM SHALL be reversible, and the up → down →
up round trip SHALL pass.

8.4. WHEN the catalog module is linted THE SYSTEM SHALL satisfy the import-linter
contracts: the domain imports no framework, and layers point inward.

8.5. WHEN routes or schemas change THE SYSTEM SHALL have `packages/api-client`
regenerated, so CI's contract gate passes.

8.6. WHEN the API test suite runs THE SYSTEM SHALL keep total coverage at or above 90 %,
and the web suite at or above 85 %.
