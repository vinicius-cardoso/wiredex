# Requirements Document

## Introduction

The firmware viewer, the second of three specs in `v0.7.0` Firmware. It delivers the phase's
roadmap line *Syntax-highlighted viewer, copy per file, diff between versions*, and the last point
of [ADR 0006](../../../docs/adr/0006-firmware-snapshots.md)'s decision: *the UI offers a
syntax-highlighted viewer, one-click copy per file and a diff between versions*. It works on what
[13-firmware-versions](../13-firmware-versions/design.md) stores and answers, each version's source
files with their text, and changes nothing in the API: highlighting, copying and comparing all
happen in the browser. It also settles the item
[docs/design/visual-identity.md](../../../docs/design/visual-identity.md) left open, *a
syntax-highlighting theme derived from these tokens*.
[15-flash-log](../15-flash-log/requirements.md) follows and closes the phase.
[design.md](design.md) answers these.

Acceptance criteria use EARS: `WHEN <condition> THE SYSTEM SHALL <behaviour>`. Every criterion
acts inside the caller's workspace, through 13's reads.

Owner decisions (2026-09-27) that bind every spec and reach this one: one PR per spec with
auto-merge, and the release PR waits for the phase's last spec (15-flash-log), which only the owner
merges. This spec carries no `Release-As` footer.

The visual identity (2026-09-22) binds every screen here: colours come from the theme tokens, status
is never shown by colour alone, and there is one mono face, Roboto Mono, for firmware source and
diffs.

## Glossary

- **The owner**: the single real user. A guest acts the same way inside their demo bench.
- **Viewer**: how a version's source file is shown: its text, with line numbers and highlighting.
- **Language**: what a file is highlighted as, chosen by its extension: C++ (Arduino sketches, C and
  C++ sources and headers), Python, JSON, or plain text.
- **Token**: a run of text the highlighter styles as one thing: a keyword, a string, a comment.
- **Wrap**: long lines broken at the box's width instead of scrolling sideways.
- **Comparison**: what changed from one version of a firmware to another: which files were added,
  removed or changed, and in each changed file, which lines.
- **From** and **To**: the two versions of a comparison, the state before and the state after.
- **Hunk**: a run of changed lines with up to three unchanged lines of context around it.
- **Base**: the version a draft was started from (13).

## Requirements

### Requirement 1: Highlighting

**User Story:** As the owner, I want a sketch shown with its keywords, strings and comments told
apart, so that reading it on the bench is as easy as in the IDE.

#### Acceptance Criteria

1. WHEN a source file is shown THE SYSTEM SHALL highlight it as C++ when its path ends in `.ino`,
   `.c`, `.cc`, `.cpp`, `.cxx`, `.h`, `.hh`, `.hpp` or `.hxx`, as Python for `.py`, as JSON for
   `.json`, and as plain text otherwise, comparing extensions ignoring case.
2. WHEN a file is highlighted THE SYSTEM SHALL show exactly its stored text, character for
   character, the tokens changing only how it looks.
3. WHEN a file's text doesn't parse in its language THE SYSTEM SHALL still show all of it,
   highlighting what it can.
4. WHEN a file has more than 5,000 lines or more than 256 KB THE SYSTEM SHALL show it as plain text
   without line numbers, saying why.
5. WHEN a version is shown THE SYSTEM SHALL show each file's text at once as plain text and add the
   highlighting when it is ready, never holding the text back for it.

### Requirement 2: Reading a file

**User Story:** As the owner, I want line numbers and a choice of wrapping, so that I find line 42
of a compiler error and read long lines on my phone.

#### Acceptance Criteria

1. WHEN a file within requirement 1.4's limits is shown THE SYSTEM SHALL number its lines from 1,
   in a gutter that is neither selected nor copied with the text and that screen readers skip.
2. WHEN *Wrap long lines* is switched THE SYSTEM SHALL break long lines at the box's width while it
   is on, and scroll them inside the box while it is off.
3. WHEN *Wrap long lines* is switched THE SYSTEM SHALL remember the choice on this device.
4. WHEN a file's box scrolls THE SYSTEM SHALL let the keyboard reach and scroll it, the box named
   by its file's path.
5. WHEN an empty file is shown THE SYSTEM SHALL say it is empty.

### Requirement 3: Copy per file

**User Story:** As the owner, I want to copy a whole file in one click, so that pasting it into the
Arduino IDE is all it takes before flashing.

#### Acceptance Criteria

1. WHEN *Copy* is chosen on a file THE SYSTEM SHALL put exactly the file's stored text on the
   clipboard, with no line numbers and no wrapping.
2. WHEN a file is copied THE SYSTEM SHALL announce which file was copied, in a status message a
   screen reader reads.
3. WHEN the clipboard can't be written THE SYSTEM SHALL select the file's text and say how to copy
   it with the keyboard.
4. WHEN a file of a draft or of a released version is shown THE SYSTEM SHALL offer *Copy* on it.

### Requirement 4: Comparing versions

**User Story:** As the owner, I want to see what changed between two versions, so that I know what
a board gains when I flash the newer one.

#### Acceptance Criteria

1. WHEN two versions of one firmware are compared THE SYSTEM SHALL match their files by path,
   ignoring case, and list each file as added, removed, changed or unchanged.
2. WHEN a changed file is shown THE SYSTEM SHALL show its changes as hunks, each changed line marked
   added or removed, every line numbered as it is in the version it comes from, with up to three
   unchanged lines of context around each hunk.
3. WHEN an added or a removed file is shown THE SYSTEM SHALL show all of its lines as added or
   removed.
4. WHEN a comparison is shown THE SYSTEM SHALL say how many files were added, removed and changed
   and how many lines were added and removed, and name the unchanged files without their text.
5. WHEN two versions hold the same files with the same text THE SYSTEM SHALL say they are the same.
6. WHEN a comparison is opened from a version THE SYSTEM SHALL compare that version with its base
   when the base is a version of the same firmware, or else with the next lower version, and offer
   both sides as choices among all of the firmware's versions, drafts included.
7. WHEN the versions compared change THE SYSTEM SHALL keep them in the address, so a comparison can
   be bookmarked and walked with Back.
8. WHEN a comparison names a version that isn't one of the firmware's, or the same version on both
   sides, THE SYSTEM SHALL say so and offer the choice again.
9. WHEN a file's changes would take more than one second to compute THE SYSTEM SHALL show the file
   as changed, with its sizes, instead of its lines.

### Requirement 5: How changes read

**User Story:** As the owner, I want added and removed lines told apart without relying on colour,
so that a comparison reads the same to everyone.

#### Acceptance Criteria

1. WHEN a line is shown as added or removed THE SYSTEM SHALL mark it with `+` or `−` and the word
   *added* or *removed* for screen readers, and tint its gutter from the theme's `ok` or `crit`
   token.
2. WHEN a changed file within requirement 1.4's limits is shown THE SYSTEM SHALL highlight its
   lines in the file's language, as the viewer does.
3. WHEN a changed file is shown THE SYSTEM SHALL show it as a table with a caption, its columns the
   old line number, the new line number, the change and the text.

### Requirement 6: The syntax theme

**User Story:** As the owner, I want highlighting that belongs to Wiredex's palette, in light and
dark, so that source reads as part of the app.

#### Acceptance Criteria

1. WHEN source is highlighted THE SYSTEM SHALL colour each kind of token from the existing theme
   tokens, adding no new colour value.
2. WHEN a colour is used for text in a code box THE SYSTEM SHALL keep a contrast of at least 4.5:1
   against the box, in both the light and the dark theme.
3. WHEN highlighted source is shown THE SYSTEM SHALL style it only through the site's own
   stylesheet, adding no inline `<style>` element, so the Content Security Policy's
   `style-src 'self'` holds.

### Requirement 7: Web

**User Story:** As the owner, I want the viewer and the comparison to work like every other screen,
so that nothing about them is special to learn.

#### Acceptance Criteria

1. WHEN a viewer or comparison screen is rendered THE SYSTEM SHALL take every string from an i18n
   key present in both `en.json` and `pt-BR.json`, and every colour from a theme token.
2. WHEN those screens are operated by keyboard alone THE SYSTEM SHALL reach every control, each
   with a role and an accessible name.
3. WHEN they are shown on a phone-width screen THE SYSTEM SHALL keep the page free of horizontal
   scrolling, long lines scrolling inside their own box.
4. WHEN a page that shows no source is opened THE SYSTEM SHALL load neither the highlighter nor the
   comparison.

### Requirement 8: Non-functional

**User Story:** As the owner, I want the viewer to add weight only where it is used, so that the
rest of the app stays as quick as it is.

#### Acceptance Criteria

1. WHEN this spec is built THE SYSTEM SHALL change no route and no schema, so `packages/api-client`
   stays as 13 left it.
2. WHEN the web suite runs THE SYSTEM SHALL keep its coverage at or above 85 %.
3. WHEN a package is added THE SYSTEM SHALL pin it to an exact version published at least a day
   before.
4. WHEN the lockfile changes THE SYSTEM SHALL pass CI's OSV scan over it.
5. WHEN highlighting and comparing are tested THE SYSTEM SHALL check, over generated inputs, that
   highlighting keeps the text and that a changed file's hunks turn its From text into its To text.

## Out of scope

- Highlighting while editing: drafts keep 13's text box.
- A side-by-side comparison, ignoring whitespace, changes within a line, and detecting renames.
- Comparing the versions of two different firmware.
- Downloading a file or a version.
- Showing changelogs as Markdown.
- More languages, such as INI, CMake, YAML or Markdown: each is one more grammar and one line in the
  extension table.
