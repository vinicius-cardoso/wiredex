# Requirements Document

## Introduction

Minimum stock and the reorder list: a part says the least to keep on hand, and Wiredex lists
the parts that fell below it. Until now a part was only reported short when a project needed
more of it than there was; a part that was simply running out said nothing.

With it comes the first workspace setting, and the page that holds settings.

It builds on [01-catalog-foundation](../01-catalog-foundation/requirements.md),
[05-inventory-stock](../05-inventory-stock/requirements.md) and
[18-dashboard](../18-dashboard/requirements.md). [design.md](design.md) answers these.

Acceptance criteria use EARS: `WHEN <condition> THE SYSTEM SHALL <behaviour>`. Every criterion
acts inside the caller's workspace.

Owner decisions (2026-10-11):

1. **A Settings page where the workspace chooses what a minimum is compared against: free
   stock or total stock. Free is the default.**
2. **A default minimum per category**, beside each part's own.

Decisions taken without the owner, for the owner to review:

1. **The category default is inherited down the tree**, as the category flags are: the nearest
   one set wins.
2. **A part's own minimum overrides its category's**, and **0 means "don't watch"**, on a part
   or on a category, so one branch or one part can opt out of an inherited default.
3. **Parts of a category that isn't stocked are never watched.** Nobody counts consumables.
4. **The setting belongs to the workspace, not the person**, and is kept on the server: the
   list has to read the same on every device, and it is the server that builds it.
5. **No notification.** Wiredex sends none; the dashboard says how many parts are below their
   minimum and the navigation has the list.
6. **The parts list has no "low" badge or filter yet.** The part page, the reorder list and the
   dashboard say it.

## Requirements

### Requirement 1: a part's minimum

1. WHEN a part is created or edited with a minimum stock THE SYSTEM SHALL keep it: a whole
   number from 0 to 1,000,000.
2. WHEN it is left out or null THE SYSTEM SHALL keep none, and the part takes its category's
   default.
3. WHEN it is anything else THE SYSTEM SHALL refuse the write with 422 and change nothing.
4. THE part SHALL answer its own minimum, the minimum it is held to, and the category that one
   comes from when it isn't its own.

### Requirement 2: a category's default

1. WHEN a category's minimum stock is set THE SYSTEM SHALL keep it as the default of its parts
   and of the parts of every category under it that sets none.
2. WHEN it is cleared THE SYSTEM SHALL inherit the parent's again.
3. WHEN a category patch doesn't mention it THE SYSTEM SHALL leave it as it is.
4. THE category SHALL answer the minimum set on it and the one its parts take.

### Requirement 3: the reorder list

1. THE SYSTEM SHALL list every live part whose stock is below the minimum it is held to, with
   what there is, the minimum, how many are missing, its category, and the category the minimum
   comes from when it isn't the part's own.
2. THE list SHALL be ordered by how much of the minimum is there, least first, then by name.
3. A part held to no minimum, or to 0, SHALL NOT be listed; nor a part of a category that isn't
   stocked; nor a part in the trash.
4. A part exactly at its minimum SHALL NOT be listed.
5. THE list SHALL say which basis it was compared by.
6. THE list SHALL cost the same number of reads whatever the number of parts.

### Requirement 4: the setting

1. THE workspace SHALL have a stock basis: `free`, on hand and not reserved, or `total`,
   everything on hand. A workspace that never chose one has `free`.
2. WHEN the basis is saved THE SYSTEM SHALL keep it for that workspace only, and the reorder
   list and the part page SHALL compare by it from then on.
3. WHEN the basis saved is the one already kept THE SYSTEM SHALL write nothing more.
4. Another workspace's settings SHALL be neither readable nor writable (ADR 0007).

### Requirement 5: the pages

1. THE part form SHALL offer the minimum, say what a blank field means (none, or the
   category's default by its number), and not offer it for a part nobody stocks.
2. THE part page SHALL show the minimum the part is held to and where it comes from, and, when
   the part is below it, what there is and how many are missing, by the workspace's basis.
3. THE categories page SHALL offer the default minimum of the selected category and say what it
   inherits while it sets none.
4. THE reorder page SHALL show the list, say what it was compared against with a link to change
   it, and say how to start when it is empty.
5. THE dashboard SHALL say how many parts are below their minimum, linking to the list, and say
   nothing when there are none.
6. THE Settings page SHALL offer the two bases with what each means, save a choice as it is
   picked, and say that it saved or that it couldn't.
7. Settings SHALL be reachable from the account menu, the reorder list from the navigation, and
   both from the command palette.
8. Every string SHALL exist in English and Brazilian Portuguese.

### Requirement 6: the release before this one

1. THE migration SHALL only add nullable columns and a new table, and its `downgrade` SHALL
   remove them.
