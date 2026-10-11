# Requirements Document

## Introduction

Workspace settings: four more choices on the Settings page that
[24-minimum-stock](../24-minimum-stock/requirements.md) started. [design.md](design.md)
answers these.

Acceptance criteria use EARS: `WHEN <condition> THE SYSTEM SHALL <behaviour>`. Every criterion
acts inside the caller's workspace.

Owner decisions (2026-10-11):

1. **The theme and the language stay in the header**, not on the Settings page.
2. **Four settings join it: a default minimum stock, the short-code prefix, the date and number
   format, and how long the trash keeps things.**

Decisions taken without the owner, for the owner to review:

1. **Every setting is the workspace's, kept on the server**, as the stock basis is.
2. **A code already given keeps its prefix.** Codes are printed on drawer labels; a new prefix
   codes what is created from then on, and the numbers go on from where they are, so no code
   is ever given twice.
3. **The prefix is a letter and up to five letters or digits**, upper case, so a code still
   fits on a label and in 16 characters.
4. **The default minimum comes last**: a part's own minimum, then its categories', then the
   workspace's. A 0 set on a part or a category still means "don't watch", the default
   included.
5. **The trash is kept for ever unless a number of days is chosen**, which is what it did
   before. The sweep runs nightly, before the file prune, so the files of what it deletes go
   the same night.
6. **Fixed date formats use a 24-hour clock**; "as the language does" keeps each language's
   own.
7. **Numbers written through the app's formatter follow the setting**: counts, file sizes.
   Counts inside sentences are left as the sentence writes them.

## Requirements

### Requirement 1: the settings

1. THE workspace SHALL have, besides its stock basis, a default minimum stock (none, or 0 to
   1,000,000), a code prefix (`WX` unless chosen), a date format (`language`, `iso`, `dmy`,
   `mdy`), a number format (`language`, `point`, `comma`) and a trash retention (none, or 1 to
   3,650 days).
2. WHEN the settings are saved THE SYSTEM SHALL replace them whole, and write nothing when they
   are the ones kept.
3. WHEN a setting isn't one of its options THE SYSTEM SHALL refuse the save with 422, saying
   what it should be, and keep what was there.
4. THE migration SHALL only add columns that are nullable or have a default.

### Requirement 2: the default minimum

1. WHEN a part sets no minimum and none of its categories does THE SYSTEM SHALL hold it to the
   workspace's default, on its page and on the reorder list, and say the minimum is the
   workspace's.
2. A part or a category whose minimum is set, 0 included, SHALL NOT take the default.
3. A part nobody stocks SHALL NOT take it.

### Requirement 3: the code prefix

1. WHEN a location or a unit is created, received, quick-added or imported THE SYSTEM SHALL
   code it with the workspace's prefix.
2. A code already given SHALL keep its prefix, and SHALL still be found by it.

### Requirement 4: formats

1. THE web app SHALL write every date and every count it formats in the chosen format.

### Requirement 5: the trash

1. WHEN `wiredex trash prune` runs THE SYSTEM SHALL delete for good, in every workspace that
   keeps its trash for a number of days, each record that went to the trash longer ago than
   that, with what it holds; and touch nothing in a workspace that keeps it for ever.
2. THE nightly service SHALL run it after the demo reset and before the file prune.
3. THE trash page SHALL say how long the trash is kept, with a link to change it.

### Requirement 6: the page

1. THE Settings page SHALL hold the stock, codes, formats and trash sections, each setting
   saved as it is changed, with an example or a sentence saying what it does.
2. WHEN several settings are changed before the first is saved THE SYSTEM SHALL keep every one.
3. Every string SHALL exist in English and Brazilian Portuguese.
