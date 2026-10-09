# Implementation Plan

## Overview

Seven tasks that build [design.md](design.md) against [requirements.md](requirements.md).

One migration, `0024`. No new module and no new route.

Branch first: `git switch -c feat/firmware-builds` from `feat/browser-flash`, which this builds
on, and never commit this spec's work on `main`.

One task, one commit, each passing `make check` **on its own** (AGENTS.md). `make coverage` on
tasks 1 to 4; `make client` on task 1, the regenerated client in that commit. Tick the task in
this file in the same commit.

## Tasks

- [ ] 1. Files: a firmware version as a subject, a build as a kind
  - `SubjectKind.FIRMWARE_VERSION`, `AttachmentKind.FIRMWARE_BUILD`, zip only, the pairing rule
    on upload and re-kind; migration `0024`; the regenerated client; the web's kind label.
  - `feat(files): attach a build to a firmware version`
  - _Requirements: 1.1, 1.2, 1.4, 1.5, 1.8_

- [ ] 2. Firmware and bootstrap: which versions take a build, and which keep one
  - `VersionIsReleased`, `VersionIsKept`, `FirmwareVersions.kept`; `AttachmentSubjects`' arm.
  - `feat(firmware): let a released version be an attachment's subject`
  - _Requirements: 1.3, 1.6, 1.7_

- [ ] 3. The build command's parts
  - `flash_args` parsing, the manifest and the zip, the `Api` protocol and its `urllib` client.
  - `feat(firmware): zip a build's binaries with their offsets`
  - _Requirements: 2.1, 5.6_

- [ ] 4. `wiredex firmware build`
  - The flow, the compiler, the CLI entry, refusals and the session's end.
  - `feat(firmware): build a version's binaries with one command`
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

- [ ] 5. Web: read a build and flash it
  - `bundle.ts`, `useStoredBuild`, the dialog's *Binaries from* choice.
  - `feat(web): flash a version's stored build without choosing files`
  - _Requirements: 2.2, 3.1, 3.2, 3.3, 3.4, 3.5_

- [ ] 6. Web: a version's builds on its panel
  - `BuildsSection`; the e2e journey.
  - `feat(web): list and add a released version's builds`
  - _Requirements: 4.1, 4.2_

- [ ] 7. Documents
  - ADR 0006's amendment, ADR 0013, the architecture document and the README, with their twins;
    the self-hosting note on `arduino-cli`.
  - `docs: describe stored firmware builds and the build command`
