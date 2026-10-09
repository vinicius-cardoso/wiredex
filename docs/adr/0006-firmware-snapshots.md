# 0006. Firmware as versioned source snapshots and a per-unit flash log

- **Status:** Accepted, amended 2026-10-09 (see *Amendment* below)
- **Date:** 2026-09-22

## Context

The goal is simple: know which code is on which board, and get the code back
to paste into the Arduino IDE (or any other tool). Building, storing binaries
or flashing from the browser are out of scope for now.

## Decision

- `Firmware` (name, target board such as `esp32:esp32:esp32`, framework, linked
  revision) has `FirmwareVersion`s: a SemVer, a changelog, and a set of **source
  files** (path + text). A single `.ino` is the common case, and multi-file
  sketches work too.
- A version is **immutable once released**. Changes mean a new version.
- A **deployment log** records `unit ← version` flashes with a date and notes.
  A unit's current firmware is its latest deployment.
- The UI offers a syntax-highlighted viewer, one-click copy per file and a diff
  between versions.

## Implementation (v0.7)

Built by three specs: the versions, the viewer, then the flash log.

**Versions** (13-firmware-versions):

- **A `firmware` module of its own**, with four tables isolated by workspace: `firmware`,
  `firmware_revisions`, `firmware_versions` and `source_files`.
- **A firmware runs on any number of revisions**, not one: the weather station's sketch runs on
  breadboard `A` and perfboard `B`. Firmware keeps the links, not projects, so they are made and
  removed whatever the revision's status: what a built board runs keeps changing. A link is a
  bare revision id, resolved at every read, and one whose revision is gone is left out. A fork
  copies its source's links through 08's revision contents, in the fork's transaction.
- **A version number is SemVer 2.0.0, lower-cased, without build metadata.** A leading `v` is
  dropped and build metadata is refused, so the order is total and the canonical text is unique
  per firmware. The suggested number is the successor of the highest, so it is always free; a
  suggestion longer than 64 characters, a typed number's cap, is refused and asks for a number
  to be typed.
- **A release needs a file and a changelog, and freezes the number, the changelog and the
  files.** A draft starts empty or from any version of its firmware, and drafts may coexist.
  Every write locks its firmware's row first.
- **Source is kept byte for byte but for line endings**: CRLF and a lone CR become LF. A version
  holds at most 100 files and 1 MiB of UTF-8, `.ino` files first, the Arduino IDE's main tab.
  Paths are unique ignoring case and refuse what breaks a path on Linux, macOS or Windows, but
  for two things only Windows refuses, which are accepted: device names (`CON`, `aux.h`) and a
  part ending in a dot or a space.
- **No value holds what PostgreSQL can't store**: a NUL, or half of a surrogate pair from a JSON
  escape. Each value refuses it on its own field, with its own code, so it never becomes a 500.

**Viewer** (14-firmware-viewer):

- **CodeMirror 6's parsers, without its editor view**, which mounts its theme as an inline
  `<style>` that the CSP's `style-src 'self'` refuses. Lezer grammars parse C++ (`.ino` and the C
  and C++ extensions), Python and JSON, and `@lezer/highlight` tags each token with a class, so
  the code is plain DOM a screen reader reads. Any other file, or one past 5,000 lines or
  256 KiB, shows as plain text. Drafts are still written in 13's plain text box.
- **The syntax theme is drawn from the tokens** (`source/syntax.css`): no colour is added, and
  dark mode follows. `void` and `int` read as type names, as the C++ grammar tags them.
- **Copy writes the stored text**, so line numbers and wrapping never leak into it, and selects
  the file for Ctrl+C where the clipboard refuses.
- **A comparison is computed in the browser with jsdiff**, from the two versions' reads and with
  no route: files matched by folded path, hunks with three lines of context. A window of
  64rem or more shows the two versions side by side, as an editor's diff does, with the words
  that changed inside a line marked; a narrower one shows one column of changes.
- The highlighter with its grammars, and jsdiff with the comparison, load in lazy chunks, the
  app's first. Until a chunk arrives, a file shows as plain text.

**Flash log** (15-flash-log):

- **A flash is a row of `flashes`**, the decision's *deployment*, in firmware and isolated by
  workspace. Its unit is a bare id; its version is a key into `firmware_versions` with
  `ON DELETE RESTRICT`.
- **Only a released version is flashed**, since a draft can still change. A test build is a
  released pre-release, such as `1.3.0-rc.1`.
- **A flash records its unit's code and revision as they were** when it is logged, so the log
  still names the board after the unit is deleted, and its build after a dismantle.
- **The current version is the newest by flash time**, then by logging, so a flash backdated to
  last week joins the history without becoming current. A time left as the dialog opened is sent
  as none, and the API's clock dates the flash. A flash is removed, never edited, and removing
  the newest makes the one before it current.
- **A flashed version is kept, and so is its firmware.** Deleting either is refused, listing the
  flashes in the way, each removable there; that is also how a deleted unit's entries go.
- **A retired unit isn't flashed, and a deleted unit keeps its log**, as inventory keeps its
  movements. A firmware's boards are the units whose newest flash is its, leaving out retired
  and deleted units.

## Implementation (v0.8)

- **A firmware goes to the trash with its versions, source files and runs-on links**
  (16-soft-delete-and-trash, [ADR 0014](0014-soft-delete-and-trash.md)). A firmware one of whose
  versions a flash names can't be moved to the trash, just as it couldn't be deleted. A version
  on its own is still deleted at once. While a firmware is in the trash it keeps its name, and a
  new firmware with that name is refused with `name_in_trash`.
- **A unit in the trash is absent**, so it can't be flashed. A flash already queued behind the
  move finds no unit.
- **History records a firmware as one record** with its versions, source files and links, and
  each flash under its unit ([ADR 0015](0015-history-by-triggers.md)). Restoring an earlier
  version puts back the firmware's name, target, framework and description only. A released
  version's files stay as they are, and deleted rows are never re-created from history.

## Amendment (2026-10-09): flashing from the browser

The context above left flashing from the browser out of scope. It is now in, without
changing what is stored:

- **The browser writes the board, the API only logs it.** esptool-js speaks the ESP
  loader's protocol over Web Serial, so the write happens between the page and the USB
  port. No route, table or migration is added; a flash made this way is the same row of
  `flashes` as one logged by hand, dated by the API's clock.
- **Binaries are chosen from disk and not stored.** A version is still its source. The
  owner picks the `.bin` files their build exported, each with an offset suggested from
  its name and the firmware's board, and they never leave the computer. So Wiredex can't
  prove a binary was built from the version it is logged as; that link is the owner's
  word, as it already was for a flash logged by hand. Storing binaries stays possible
  later.
- **Nothing is logged unless the write is verified.** Each binary's MD5 is read back from
  the flash and compared. When the write is verified but logging is refused, the dialog
  keeps the result and offers to log it again rather than writing twice.
- **A write that would stop the board from starting is refused before it begins**: an
  offset that isn't a sector's start, two binaries sharing a sector, a bootloader away
  from where the chip that answered starts, or a binary past the end of its flash. The
  image headers are written as built (`keep` for mode, frequency and size).
- **A write isn't left half done by the page**: the dialog can't be closed while it runs,
  and leaving the page asks first.
- **ESP chips in Chromium only.** Web Serial exists in Chrome and Edge on a computer, on
  a secure origin. Elsewhere the dialog says so. Other chip families (AVR, RP2040, STM32)
  are still flashed with their own tools and logged by hand.
- **Not covered by the end-to-end journeys**, which have no serial port: the dialog is
  tested against a fake loader, and the loader wrapper against a fake esptool-js.

## Consequences

- Answers "what's running on the greenhouse ESP32?" instantly.
- Source is stored as text in Postgres, capped per version (e.g. 1 MB). Linking
  to git or storing binaries stays possible later.
