# Implementation Plan

## Overview

Six tasks that build [design.md](design.md) against [requirements.md](requirements.md).

One migration, `0024`. No new module and no new route.

Branch first: `git switch -c feat/firmware-builds` from `feat/browser-flash`, which this builds
on, and never commit this spec's work on `main`.

One task, one commit, each passing `make check` **on its own** (AGENTS.md). `make coverage` on
tasks 1 to 3; `make client` on task 2, the regenerated client in that commit. Tick the task in
this file in the same commit.

## Tasks

- [x] 1. Firmware: which versions take a build, and which keep one
  - `VersionIsReleased`, `VersionIsKept`, `Versions.kept` with its SQL and fake.
  - `feat(firmware): say which versions take a build and which keep one`
  - _Requirements: 1.3, 1.6, 1.7_

- [x] 2. Files: a firmware version as a subject, a build as a kind
  - `SubjectKind.FIRMWARE_VERSION`, `AttachmentKind.FIRMWARE_BUILD`, zip only, the pairing rule
    on upload and re-kind; `AttachmentSubjects`' arm in bootstrap; migration `0024`; the
    regenerated client; the web's kind label.
  - `feat(files): attach a build to a released firmware version`
  - _Requirements: 1.1, 1.2, 1.4, 1.5, 1.8_

- [x] 3. `wiredex firmware build`
  - `bootstrap/firmware_build.py`: `flash_args` parsing, the manifest and the zip, the `Api` over
    a transport with its `urllib` one, the `arduino-cli` compiler, the flow; the CLI entry,
    its refusals and the session's end.
  - Tests: the flow over a fake API and compiler, the transport against a local server, the
    compiler against a stand-in executable; integration through the real app.
  - `feat(firmware): build a version's binaries with one command`
  - _Requirements: 2.1, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_

- [ ] 4. Web: read a build and flash it
  - `bundle.ts`, `useStoredBuild`, the dialog's *Binaries from* choice.
  - `feat(web): flash a version's stored build without choosing files`
  - _Requirements: 2.2, 3.1, 3.2, 3.3, 3.4, 3.5_

- [ ] 5. Web: a version's builds on its panel
  - `BuildsSection`; the e2e journey.
  - `feat(web): list and add a released version's builds`
  - _Requirements: 4.1, 4.2_

- [ ] 6. Documents
  - ADR 0006's amendment, ADR 0013, the architecture document and the README, with their twins;
    the self-hosting note on `arduino-cli`.
  - `docs: describe stored firmware builds and the build command`
