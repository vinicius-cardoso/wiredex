# Requirements Document

## Introduction

Stored firmware builds, the second step of the roadmap line *Flash firmware from the browser
(WebSerial / esptool-js)*. The first step, in [ADR 0006](../../../docs/adr/0006-firmware-snapshots.md)'s
amendment, writes binaries the owner picks from disk at every flash. This spec keeps a released
version's binaries with the version, so a board is flashed with one choice and no file picker,
and adds a command that builds them from the version's own source, so what is flashed is what
Wiredex holds.

It builds on [13-firmware-versions](../13-firmware-versions/requirements.md),
[15-flash-log](../15-flash-log/requirements.md) and
[03-files-and-attachments](../03-files-and-attachments/requirements.md), whose attachments it
reuses. [design.md](design.md) answers these.

Acceptance criteria use EARS: `WHEN <condition> THE SYSTEM SHALL <behaviour>`. Every criterion
acts inside the caller's workspace.

Owner decisions (2026-10-09): binaries are stored on the version; a local command builds them.
Compiling on the server is out: the production host has 1 GB of memory.

Decisions taken without the owner (2026-10-09), for the owner to review:

1. **A build is one zip attached to the version**: the binaries and a `manifest.json` naming
   each one's offset. Why: the files module already stores, dedupes, serves, quotas and prunes
   an attachment, and a zip is a type it accepts; one object keeps a build's binaries together.
2. **The API never opens the zip.** The command writes the manifest and the browser checks it
   before a write. Why: unpacking uploads on a 1 GB host is the risk a zip brings; the checks
   that protect a board already run in the browser.
3. **Only a released version takes a build.** Why: a draft's source can still change, and a
   build of it would outlive the text it was built from.
4. **A version may hold several builds; the newest is the one flashed.** Why: a rebuild with a
   newer toolchain shouldn't need the old one deleted first, and the list shows what was built
   when.
5. **The command logs in with the owner's email and password and ends its session when it is
   done.** Why: [ADR 0008](../../../docs/adr/0008-sessions.md)'s token login already exists for
   clients without cookies; no new kind of credential is stored.
6. **The command builds Arduino firmware with `arduino-cli`.** Other frameworks are refused
   with a sentence saying so. Why: it is what the owner's firmware uses; a build made by any
   other tool can still be zipped and uploaded by hand.
7. **Picking files from the computer stays in the dialog.** Why: a version with no build, or a
   one-off test binary, is still flashed.

## Glossary

- **Build**: the binaries compiled from a released version's source, with their offsets, kept
  as one zip.
- **Manifest**: `manifest.json` at the zip's root, naming the build's binaries and offsets.
- **Stored build**: a version's newest build, the one the flash dialog offers.

## Requirements

### Requirement 1: Keeping a build with a version

**User Story:** As the owner, I want a released version to keep its binaries, so that I flash a
board without finding files on my computer.

#### Acceptance Criteria

1. WHEN a zip is attached to a released version as a build THE SYSTEM SHALL store it as that
   version's attachment, under the limits every attachment has.
2. WHEN anything but a zip is attached to a version THE SYSTEM SHALL refuse it with 415, as a
   type the subject doesn't take.
3. WHEN a build is attached to a draft, or to a version that isn't in the workspace, THE SYSTEM
   SHALL refuse it as it refuses an attachment to a record that doesn't exist.
4. WHEN a version's builds are listed THE SYSTEM SHALL return them newest first.
5. WHEN a build is removed THE SYSTEM SHALL remove it as any attachment is removed.
6. WHEN a version is deleted THE SYSTEM SHALL stop keeping its builds, and the files prune
   SHALL sweep them.
7. WHEN a firmware is in the trash THE SYSTEM SHALL keep its versions' builds until it is
   deleted for good.
8. WHEN a build is attached to anything but a version, or a version's attachment is given
   another kind, THE SYSTEM SHALL refuse it with 422.

### Requirement 2: The build's contents

**User Story:** As the owner, I want a build to say where each binary goes, so that nothing is
typed at a flash.

#### Acceptance Criteria

1. THE manifest SHALL name its format, the board it was built for, the tool that built it, when,
   and each binary's file name and offset in bytes.
2. WHEN the browser reads a build THE SYSTEM SHALL refuse one with no manifest, a format it
   doesn't know, a binary the manifest names that the zip lacks, or offsets the flash dialog
   would refuse, saying which.

### Requirement 3: Flashing a stored build

**User Story:** As the owner, I want *Flash from the browser* to use the version's build, so
that flashing is choosing a board and connecting.

#### Acceptance Criteria

1. WHEN the dialog's version has a build THE SYSTEM SHALL offer it first, showing when it was
   built, its binaries and their offsets, and SHALL write it without a file being chosen.
2. WHEN the dialog's version has no build THE SYSTEM SHALL say so and offer files from the
   computer, as before.
3. WHEN the owner asks for files from the computer instead THE SYSTEM SHALL take them, and back.
4. WHEN a stored build can't be read THE SYSTEM SHALL say why and offer files from the computer.
5. A stored build SHALL pass the same checks before a write as files from the computer, and be
   verified and logged the same way.

### Requirement 4: A version's builds on its page

**User Story:** As the owner, I want to see and manage a version's builds, so that I know what
would be flashed.

#### Acceptance Criteria

1. WHEN a released version is open THE SYSTEM SHALL list its builds with their titles, sizes and
   dates, each downloadable and removable, and SHALL take a build's zip from the computer.
2. WHEN a draft is open THE SYSTEM SHALL show no builds and no way to add one.

### Requirement 5: Building from the version's source

**User Story:** As the owner, I want one command to compile a version and store the result, so
that the build comes from the source Wiredex holds.

#### Acceptance Criteria

1. WHEN `wiredex firmware build` is given a firmware's name and a version's number THE SYSTEM
   SHALL log in, write that version's source files to an empty folder, compile them for the
   firmware's board with `arduino-cli`, zip the binaries with their manifest, attach the zip to
   the version as a build, and end its session.
2. WHEN the version is a draft, the firmware's framework isn't Arduino, or `arduino-cli` isn't
   installed THE SYSTEM SHALL stop before compiling and say which.
3. WHEN the compile fails THE SYSTEM SHALL show the compiler's output, attach nothing and exit
   with an error.
4. WHEN the firmware or the version isn't found, or the login is refused, THE SYSTEM SHALL say
   so, attach nothing and exit with an error.
5. THE command SHALL take the password from a prompt or standard input, never from an argument,
   and SHALL end its session whether the build succeeded or not.
6. THE offsets SHALL be the ones the build itself reports, not guessed from file names.
