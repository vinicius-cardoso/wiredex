# Requirements Document

## Introduction

Firmware versions, the first of three specs in `v0.7.0` Firmware. It delivers two of the phase's
roadmap lines: *Firmware per board target, linked to revisions*, and *Versions with source files,
changelog and immutability after release*. It creates the `firmware` module that
[docs/architecture.md](../../../docs/architecture.md) §2 and §3 plan, and builds what
[ADR 0006](../../../docs/adr/0006-firmware-snapshots.md) decided: a firmware has a name, a target
board such as `esp32:esp32:esp32` and a framework; its versions carry a SemVer, a changelog and a
set of source files, a single `.ino` or a multi-file sketch; and a version never changes once it
is released. It also gives each revision of
[08-projects-and-revisions](../08-projects-and-revisions/design.md) the *firmware line*
[ADR 0003](../../../docs/adr/0003-project-revisions.md) puts there: a firmware runs on revisions,
and 08's fork extension point carries it into a fork, the first content another module keeps.

The next two specs build on it. [14-firmware-viewer](../14-firmware-viewer/requirements.md) turns
the source this spec stores and shows as plain text into a syntax-highlighted viewer with copy per
file and a diff between versions. [15-flash-log](../15-flash-log/requirements.md) records which
released version went onto which physical board, shows the current one on the unit page, keeps a
flashed version from being deleted, and closes the phase. [design.md](design.md) answers these.

Acceptance criteria use EARS: `WHEN <condition> THE SYSTEM SHALL <behaviour>`. Every criterion
acts inside the caller's workspace.

Owner decisions (2026-09-27) that bind every spec and reach this one: one PR per spec with
auto-merge, and the release PR waits for the phase's last spec (15-flash-log), which only the owner
merges, since merging it deploys to production. This spec carries no `Release-As` footer. A change
history waits for `v0.8.0` (2026-09-26), and so do soft delete and the trash view.

ADR 0006 (2026-09-22) settles the model: source is kept as text in PostgreSQL and capped per
version (*e.g. 1 MB*); a released version is immutable, and a change means a new version; building,
storing binaries and flashing from the browser are out of scope (the roadmap keeps flashing from
the browser and linking to a git repository under *Later*).

## Glossary

- **The owner**: the single real user. A guest acts the same way inside their demo bench.
- **Firmware**: one line of code for a board: a name, a board target, a framework, a description
  and its versions (ADR 0006).
- **Board target**: the board a firmware is built for, as its toolchain names it: an Arduino FQBN
  such as `esp32:esp32:esp32`, or a board name such as `RPI_PICO`.
- **Framework**: what a firmware is written against: Arduino, PlatformIO, ESP-IDF, MicroPython, or
  other.
- **Version**: one snapshot of a firmware's source, numbered by SemVer, with a changelog.
- **SemVer**: a version number `MAJOR.MINOR.PATCH`, with an optional pre-release after a hyphen
  (`1.3.0-rc.1`), ordered by the precedence of SemVer 2.0.0.
- **Draft**: a version still being written: its number, changelog and files can change.
- **Released**: a version whose number, changelog and files never change again.
- **Changelog**: what a version changed, in the owner's words.
- **Source file**: one file of a version: a path and its text.
- **Path**: a source file's name within its version, folders included: `weather_station.ino`,
  `src/sensor.cpp`.
- **Base**: the version a draft was started from, whose files it copied.
- **Suggested version**: the number a new version takes when none is typed (Requirement 5.4).
- **Latest release**: a firmware's released version of highest precedence.
- **Runs on**: a firmware linked to a revision; the firmware a revision runs is its firmware line
  (ADR 0003).
- **Revision**, **fork**, **status**: as 08-projects-and-revisions and 10-build-lifecycle define
  them.

## Requirements

### Requirement 1: Firmware

**User Story:** As the owner, I want each firmware described once, with the board it targets, so
that every sketch I flash has one place I find it again.

#### Acceptance Criteria

1. WHEN a firmware is created with a name, a board target and a framework, and optionally a
   description, THE SYSTEM SHALL store it with no versions.
2. WHEN a firmware's name is given THE SYSTEM SHALL trim it and collapse its inner whitespace, and
   refuse with 422 on the name a name that is then empty, longer than 120 characters or holds a
   control character.
3. WHEN a firmware is created or renamed with a name another firmware of the workspace holds,
   ignoring case, THE SYSTEM SHALL refuse it with 409 on the name, naming that firmware.
4. WHEN a board target is given THE SYSTEM SHALL trim it and collapse its inner whitespace, keep
   its case, and refuse with 422 on the target one that is then empty, longer than 200 characters
   or holds a control character.
5. WHEN a framework is given THE SYSTEM SHALL accept `arduino`, `platformio`, `esp_idf`,
   `micropython` or `other`, and refuse any other value with 422.
6. WHEN a firmware's description is given THE SYSTEM SHALL keep its line breaks, trim its ends,
   read a blank description as none, and refuse one longer than 4,000 characters with 422 on the
   description.
7. WHEN a firmware is edited THE SYSTEM SHALL replace its name, target, framework and description
   with the edit's, and write nothing when they are the ones it already has.
8. WHEN a firmware is opened THE SYSTEM SHALL answer its details, the revisions it runs on, its
   versions highest first with each one's status, base, file count and size, its latest release,
   and its suggested version.
9. WHEN a firmware is deleted THE SYSTEM SHALL delete it with its versions, their source files and
   its links to revisions, in one transaction.
10. WHEN a firmware that isn't in the workspace is opened, edited or deleted THE SYSTEM SHALL answer
    404.

### Requirement 2: Finding firmware

**User Story:** As the owner, I want the firmware list to open on what I changed last and to
narrow by name or board, so that the sketch for a board is one search away.

#### Acceptance Criteria

1. WHEN the firmware list is requested THE SYSTEM SHALL answer each firmware of the workspace with
   its target, framework, latest release, number of versions, number of drafts and last change.
2. WHEN the firmware list is answered THE SYSTEM SHALL order it by last change, newest first, a
   firmware's last change being the latest of when its details changed, a revision was linked or
   unlinked, and any of its versions or their files was written, released or deleted.
3. WHEN the list is narrowed by text THE SYSTEM SHALL keep the firmware whose name or target
   contains the text, ignoring case, with `%` and `_` matching only themselves.
4. WHEN no firmware matches THE SYSTEM SHALL answer an empty list with 200.

### Requirement 3: The revisions a firmware runs on

**User Story:** As the owner, I want a firmware tied to the revisions whose boards run it, so that
a revision says which code it runs and a firmware says where it runs.

#### Acceptance Criteria

1. WHEN a firmware is linked to a revision of the workspace THE SYSTEM SHALL record that it runs on
   that revision, whatever the revision's status, and write nothing when it already does.
2. WHEN a firmware is unlinked from a revision THE SYSTEM SHALL remove the link, and answer success
   when there was none.
3. WHEN a firmware is created for a revision THE SYSTEM SHALL create it and its link to that
   revision in one transaction.
4. WHEN a revision's firmware is requested THE SYSTEM SHALL answer every firmware linked to it, by
   name, each with its target, framework, latest release, number of versions and number of drafts.
5. WHEN a firmware's revisions are answered THE SYSTEM SHALL name each by its project, label and
   summary, in the order they were linked.
6. WHEN a linked revision is no longer in the workspace THE SYSTEM SHALL leave it out of every
   answer and keep the link, refusing nothing because of it.
7. WHEN a revision that isn't in the workspace is linked, named when a firmware is created, or has
   its firmware requested THE SYSTEM SHALL answer 404 and write nothing.

### Requirement 4: Forks carry the firmware line

**User Story:** As the owner, I want a revision forked from another to run the same firmware, so
that the perfboard starts with the breadboard's code as it starts with its parts and its wiring.

#### Acceptance Criteria

1. WHEN a revision is forked THE SYSTEM SHALL link the fork to every firmware its source is linked
   to, after the BOM and the netlist are copied, in the fork's transaction.
2. WHEN a fork copies links THE SYSTEM SHALL leave the source's links and every other revision's
   links unchanged.
3. WHEN any step of a fork fails THE SYSTEM SHALL write no link, as it writes no revision and no
   other content.
4. WHEN a revision is forked THE SYSTEM SHALL copy its links whatever its status, with 08's fork
   use case unchanged.

### Requirement 5: Versions

**User Story:** As the owner, I want each state of a firmware kept as a numbered version, so that
the code on a board can always be found again by its number.

#### Acceptance Criteria

1. WHEN a version number is given THE SYSTEM SHALL read, after trimming, an optional leading `v`,
   then `MAJOR.MINOR.PATCH` of non-negative integers without leading zeros, then optionally a
   hyphen and dot-separated pre-release identifiers of ASCII letters, digits and hyphens, numeric
   ones without leading zeros, store the number lower-cased, and refuse with 422 on the version any
   other text, build metadata (`+…`), or a number longer than 64 characters.
2. WHEN a version is created or renumbered with a number another version of the same firmware
   holds THE SYSTEM SHALL refuse it with 409 on the version.
3. WHEN versions are ordered THE SYSTEM SHALL order them by SemVer 2.0.0 precedence: by major, minor
   and patch; a pre-release before its release; pre-release identifiers compared left to right,
   numeric ones by value and before alphanumeric ones, which compare in ASCII order, and a shorter
   list first when the rest is equal.
4. WHEN a version is created without a number THE SYSTEM SHALL give it the suggested version:
   `0.1.0` for a firmware with no version, otherwise the successor of its highest number: for a
   number with no pre-release, the patch raised by one (`1.2.0` → `1.2.1`); for one whose last
   pre-release identifier is numeric, that identifier raised by one (`1.3.0-rc.1` → `1.3.0-rc.2`);
   otherwise `.1` appended (`1.3.0-beta` → `1.3.0-beta.1`).
5. WHEN a version is created THE SYSTEM SHALL create it as a draft, either empty or holding a copy
   of every source file of the version of the same firmware it is started from, and record that
   version as its base.
6. WHEN a version's changelog is given THE SYSTEM SHALL keep its line breaks, trim its ends, read a
   blank changelog as none, and refuse one longer than 4,000 characters with 422 on the changelog.
7. WHEN a draft is edited THE SYSTEM SHALL replace its number and changelog with the edit's, its own
   number not counting against it, and write nothing when they are the ones it already has.
8. WHEN a version is opened THE SYSTEM SHALL answer its number, status, changelog, base, release
   date and whether it can be edited, its source files with their text, size and line count in the
   order of Requirement 7.10, and the version's total size and limits.
9. WHEN a version that isn't in the workspace is opened, edited, released or deleted, or a version
   of another firmware is named as a base, THE SYSTEM SHALL answer 404 and write nothing.

### Requirement 6: Release and immutability

**User Story:** As the owner, I want a released version frozen, so that a number written in a
board's log always means the same code.

#### Acceptance Criteria

1. WHEN a draft is released THE SYSTEM SHALL mark it released and record when.
2. WHEN a draft with no source file is released THE SYSTEM SHALL refuse it with 409 and change
   nothing.
3. WHEN a draft with no changelog is released THE SYSTEM SHALL refuse it with 409 on the changelog
   and change nothing.
4. WHEN a released version's number or changelog is edited, a source file is added to it, or one of
   its files is edited or removed, THE SYSTEM SHALL refuse it with 409 and change nothing.
5. WHEN a released version is released again THE SYSTEM SHALL refuse it with 409.
6. WHEN a released version is the base of a new version THE SYSTEM SHALL copy its files into the new
   draft and leave it unchanged.
7. WHEN writes to one firmware and its versions arrive concurrently THE SYSTEM SHALL apply them one
   at a time, so version numbers stay distinct and no file is written to a version after its
   release commits.

### Requirement 7: Source files

**User Story:** As the owner, I want a version's files stored exactly as I wrote them, so that what
I copy back into the Arduino IDE compiles as it did.

#### Acceptance Criteria

1. WHEN source files are added to a draft THE SYSTEM SHALL add one or several in one request, all of
   them or none.
2. WHEN a path is given THE SYSTEM SHALL normalize it to Unicode NFC, trim it and read `\` as `/`,
   and refuse with 422 on the path, naming it, a path that is then empty or longer than 200
   characters, starts with `/`, holds an empty, `.` or `..` segment, or holds a control character
   or one of `< > : " | ? *`.
3. WHEN a path is given that another file of the version holds, ignoring case, or that names a
   folder of another file's path, or whose folders include another file's path, THE SYSTEM SHALL
   refuse it with 409 on the path, naming both.
4. WHEN a file's text is stored THE SYSTEM SHALL store it exactly as given, except that CRLF and
   lone CR line endings become LF: tabs, trailing spaces, blank lines and the presence or absence
   of a final line break are kept.
5. WHEN a file's text holds a NUL character or isn't valid Unicode THE SYSTEM SHALL refuse it with
   422 on the content, naming the file.
6. WHEN a version would hold more than 100 files THE SYSTEM SHALL refuse the write with 422.
7. WHEN a version's files would add up to more than 1 MB (1,048,576 bytes of UTF-8) THE SYSTEM
   SHALL refuse the write with 422, saying how much room is left.
8. WHEN a draft's file is edited THE SYSTEM SHALL replace its path and text with the edit's, its own
   path not counting against it, and write nothing when they are the ones it already has.
9. WHEN a draft's file is removed THE SYSTEM SHALL delete it.
10. WHEN a version's files are listed THE SYSTEM SHALL list the `.ino` files first, then the others,
    each group by path compared ignoring case.
11. WHEN a file is edited or removed under a version that doesn't hold it THE SYSTEM SHALL answer
    404.

### Requirement 8: Removing versions

**User Story:** As the owner, I want to remove a version I started by mistake, so that the list of
versions stays true to what I wrote.

#### Acceptance Criteria

1. WHEN a version is deleted THE SYSTEM SHALL delete it with its source files, whether it is a draft
   or released.
2. WHEN a version other versions were based on is deleted THE SYSTEM SHALL keep those versions and
   clear their base.
3. WHEN a version is deleted THE SYSTEM SHALL leave the firmware's other versions unchanged.

### Requirement 9: Workspace isolation

**User Story:** As the owner, I want a guest's firmware kept inside their bench, so that lending a
demo account stays safe.

#### Acceptance Criteria

1. WHEN the application connects as its non-owner database role THE SYSTEM SHALL have row-level
   security deny reads and writes of another workspace's firmware, links, versions and source
   files.
2. WHEN a firmware, version, source file or revision of another workspace is named by id THE SYSTEM
   SHALL answer 404, not 403.
3. WHEN the firmware list or a revision's firmware is requested THE SYSTEM SHALL include no other
   workspace's firmware.
4. WHEN a link, version or source file is written THE SYSTEM SHALL have the database refuse it
   unless the firmware or version it belongs to is in the same workspace.
5. WHEN a firmware request carries no valid session THE SYSTEM SHALL answer 401 and touch nothing.
6. WHEN a firmware write carries no CSRF header THE SYSTEM SHALL answer 403 and touch nothing.

### Requirement 10: The demo workspace

**User Story:** As the owner, I want a guest's bench to open with sample firmware, so that a demo
shows what versions and releases are for.

#### Acceptance Criteria

1. WHEN a demo bench is restored THE SYSTEM SHALL restore its sample firmware after its sample
   projects: *Weather station* running on the sample weather station's revisions `A` and `B`, with
   `1.0.0` and `1.1.0` released and `1.2.0` a draft started from `1.1.0`; *Greenhouse controller*
   running on the greenhouse's `A`, with `0.1.0` released; and *Pico blink*, a MicroPython firmware
   running on no revision, with `1.0.0` and `1.1.0` released.
2. WHEN the sample firmware is restored THE SYSTEM SHALL write it through the firmware use cases, so
   it obeys every rule a firmware written in the browser does.
3. WHEN the sample sources are written THE SYSTEM SHALL have them use the pins the sample netlists
   wire.
4. WHEN a demo reset runs again THE SYSTEM SHALL remove the firmware a guest added or changed and
   put the samples back as they were.
5. WHEN a guest is invited THE SYSTEM SHALL seed the new bench with the same sample firmware the
   nightly reset restores.

### Requirement 11: Web

**User Story:** As the owner, I want firmware in the browser beside my projects, so that writing a
version down is part of flashing a board.

#### Acceptance Criteria

1. WHEN the signed-in app is shown THE SYSTEM SHALL offer *Firmware* in the main navigation, after
   *Projects*.
2. WHEN the firmware list is opened THE SYSTEM SHALL list the firmware with their targets,
   frameworks, latest releases and last changes, narrowed by a search box kept in the address.
3. WHEN a new firmware is saved THE SYSTEM SHALL open its page.
4. WHEN a new firmware is started from a revision THE SYSTEM SHALL say which revision it will run
   on before it is saved, and link it to that revision.
5. WHEN a firmware's page is opened without naming a version THE SYSTEM SHALL open its highest
   version, and list every version with its status, each reachable by a link, the open one marked.
6. WHEN a version is shown THE SYSTEM SHALL show its number, status, base, release date, changelog
   and files, each file's text in the mono face under its path with its size and line count, and
   offer to edit it, release it, start a new version from it and delete it, editing and releasing
   only for a draft.
7. WHEN a draft is released in the browser THE SYSTEM SHALL ask first, saying its files and
   changelog won't change again, and keep *Release* unavailable, saying why, while the draft has no
   file or no changelog.
8. WHEN a new version is started in the browser THE SYSTEM SHALL offer the suggested number and the
   version to start from, defaulting to the version it was started from, or else the highest,
   with an empty version as a choice.
9. WHEN a draft's files are written in the browser THE SYSTEM SHALL let a file be added by typing or
   pasting its path and text, several be added from files chosen on the computer, and each be
   edited, renamed and removed, the text box keeping the text exactly as typed.
10. WHEN a file chosen on the computer isn't text, or the files chosen would pass the version's
    limits, THE SYSTEM SHALL say so before sending anything.
11. WHEN a revision is shown THE SYSTEM SHALL show the firmware it runs, each with its latest
    release, and let a firmware of the workspace be linked to it, a linked one be unlinked, and a
    new firmware be started for it.
12. WHEN a firmware, version, file or link changes THE SYSTEM SHALL refresh the affected list, page
    and revision in place, without a full reload.
13. WHEN any firmware screen is rendered THE SYSTEM SHALL take every string from an i18n key present
    in both `en.json` and `pt-BR.json`, and every colour from a theme token.
14. WHEN those screens are operated by keyboard alone THE SYSTEM SHALL reach every control, each with
    a role and an accessible name.
15. WHEN Tab is pressed in a file's text box THE SYSTEM SHALL move the focus on rather than type a
    tab, so the keyboard is never trapped.
16. WHEN a firmware screen is shown on a phone-width screen THE SYSTEM SHALL keep the page free of
    horizontal scrolling, a long line of source or a wide table scrolling inside its own box.

### Requirement 12: Non-functional

**User Story:** As the owner, I want firmware to keep the architecture's lines, so that the viewer
and the flash log build on it without rework.

#### Acceptance Criteria

1. WHEN the API is linted THE SYSTEM SHALL satisfy the import-linter contracts with `firmware` as a
   module of its own: its domain imports no framework, its layers point inward, it imports no
   other module, and only the composition root connects it to `projects`.
2. WHEN migration `0020` is applied THE SYSTEM SHALL only add tables, in a migration that passes the
   up → down → up round trip.
3. WHEN a firmware, the firmware list, a revision's firmware or a version is read THE SYSTEM SHALL
   use a fixed number of queries, whatever the number of firmware, versions, files and links.
4. WHEN routes or schemas change THE SYSTEM SHALL have `packages/api-client` regenerated, so CI's
   contract gate passes.
5. WHEN the API test suite runs THE SYSTEM SHALL keep total coverage at or above 90 %, and the web
   suite at or above 85 %.
6. WHEN version numbers, their order and the suggested version, paths, text, a version's limits and
   file order, immutability after release and the fork's copy are tested THE SYSTEM SHALL check
   them with Hypothesis.

## Out of scope

- Syntax highlighting, copy per file and the diff between versions (14-firmware-viewer).
- The flash log, the current version on the unit page, and keeping a flashed version from being
  deleted (15-flash-log).
- Building, storing binaries, flashing from the browser and linking to a git repository (ADR 0006,
  *Later*).
- Downloading a version as a ZIP, choosing a whole folder or a ZIP to upload, and files that aren't
  text.
- A pin map beside the source drawn from the revision's netlist (12's `Nets.uses_of_part` seam).
- Which designator of a revision's BOM a firmware runs on, for a revision with two boards.
- A history of firmware edits, soft delete and the trash (`v0.8.0`).
