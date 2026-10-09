# Design Document: firmware builds

## Overview

A released version's binaries are kept as one zip, a **build**, attached to the version through
the files module, and `wiredex firmware build` makes one from the version's source. The flash
dialog ([ADR 0006](../../../docs/adr/0006-firmware-snapshots.md)'s amendment) then writes the
stored build without a file picker. Answers [requirements.md](requirements.md).

## Architecture

```
wiredex firmware build ──token login──▶ API ──▶ firmware (source)        files (attachment)
        │  arduino-cli compile                                               ▲
        └────────── POST /api/attachments  subject=firmware_version:<id> ────┘
browser: GET attachments → GET content (zip) → unzip → checks → esptool-js → POST flash
```

No table. One migration widens two CHECK constraints. No new route: a build is an attachment.

## Components and Interfaces

### files: a fourth subject and a seventh kind

- `SubjectKind.FIRMWARE_VERSION = "firmware_version"` (16 characters, the column's length) and
  `AttachmentKind.FIRMWARE_BUILD = "firmware_build"`.
- `SubjectKind.accepts` takes only `application/zip` for a version (requirement 1.2).
- A new pairing rule, checked on upload and on re-kind: a version's attachment is a
  `firmware_build`, and nothing else is (1.8). A new `FilesError` subclass, 422 at the router.
- `AttachmentKind.suggested_for` answers `firmware_build` for a version.
- Listing is already newest first (03's 1.6), which is requirement 1.4.

### firmware: is a version there to build for

- `VersionIsReleased(workspace_id, version_id) -> bool`: the version is live and released. What
  `Subjects.exists` asks, so a draft reads as no such subject (1.3).
- `VersionIsKept(workspace_id, version_id) -> bool`: the version's row exists, its firmware live
  or in the trash. What the prune asks (1.6, 1.7). `FirmwareVersions.kept` is the port's new
  read, one statement, no trash filter.

### bootstrap

- `SubjectReads` gains the two reads, and `AttachmentSubjects` a `FIRMWARE_VERSION` arm in
  `exists`, `kept` and `_look_up`.
- `bootstrap/firmware_build.py` holds the command's work, and `cli.py` its `firmware build`
  entry. It is a client of the API, so it lives in the composition root and imports no module.

### The build's zip

```json
{
  "format": 1,
  "board": "esp32:esp32:esp32",
  "tool": "arduino-cli 1.3.1",
  "built_at": "2026-10-09T21:40:00Z",
  "images": [
    { "file": "blink.ino.bootloader.bin", "offset": 4096 },
    { "file": "blink.ino.partitions.bin", "offset": 32768 },
    { "file": "boot_app0.bin", "offset": 57344 },
    { "file": "blink.ino.bin", "offset": 65536 }
  ]
}
```

`manifest.json` and the binaries sit at the zip's root, deflated. The merged image is left out:
it holds the others and would erase saved settings. The attachment's title is
`Build <date> · <tool>`.

### The command

`wiredex firmware build NAME VERSION --url URL --email EMAIL [--password-stdin]
[--arduino-cli PATH]`; `WIREDEX_URL` and `WIREDEX_EMAIL` stand in for the two options.

1. `POST /api/auth/tokens` for a bearer token (ADR 0008). Every later step is in a `try` whose
   `finally` posts `/api/auth/logout` (5.5).
2. Find the firmware by exact name among `GET /api/firmware?q=`, then the version by number in
   its page; refuse a draft and a framework other than `arduino` (5.2).
3. Write the version's files under `<tmp>/<sketch>/`, the sketch named after the `.ino` listed
   first, as `arduino-cli` requires a sketch's folder to be named.
4. `arduino-cli compile --fqbn <target> --build-path <tmp>/build <sketch>`; on a non-zero exit
   print its output and stop (5.3).
5. Read `<tmp>/build/flash_args`, the offsets `arduino-cli` itself writes for esptool (5.6), and
   zip the files it names with the manifest.
6. `POST /api/attachments` as multipart.

The HTTP side is a small `Api` protocol with a `urllib` implementation, so the build's logic is
tested against a fake and production gains no dependency. The compiler is a callable taking the
sketch and build folders, faked the same way.

### Web

- `flashing/bundle.ts`: `readBundle(bytes) -> FlashImage[]`, reading the zip's central directory
  and inflating entries with the browser's `DecompressionStream("deflate-raw")`, which every
  browser with Web Serial has. Refusals are typed, one per case of requirement 2.2. No library.
- `flashing/useStoredBuild.ts`: the version's newest `firmware_build` attachment and its bundle,
  fetched when the dialog opens.
- `WriteFlashForm`: a *Binaries from* choice, *This version's build* or *This computer*. The
  stored build's binaries show as the same rows, their offsets read-only. Everything after
  `placed(images)` is unchanged, so the chip checks, the write, the verification and the log
  are shared (3.5).
- `BuildsSection` on a released version's panel: the attachments of
  `firmware_version:<id>`, each with download and remove, and a file input for a zip (4.1).

## Data Models

Migration `0024`: `ck_attachments_subject_kind` gains `'firmware_version'` and
`ck_attachments_attachment_kind` gains `'firmware_build'`. The previous release never writes
either value and reads no attachment of a version, so it runs unchanged against the new
constraints. `downgrade` deletes those attachments, then restores both CHECKs, as 0014 did.

## Correctness Properties

### Property 1: a bundle round-trips

For any set of binaries and offsets, the zip the command writes is read by `readBundle` as the
same bytes at the same offsets. Tested from the Python side by writing a fixture the web test
reads.

## Error Handling

| Case | Where | Answer |
| --- | --- | --- |
| Not a zip on a version | files | 415, a firmware version takes a build |
| A draft, or no such version | files via `Subjects` | 404, that firmware version doesn't exist |
| Kind and subject don't pair | files | 422 |
| Unreadable bundle | browser | a sentence, and files from the computer offered |
| Compile failed | command | the compiler's output, exit 1 |

## Testing Strategy

- files domain and use cases: the new kind, the zip-only rule, the pairing on upload and re-kind.
- firmware: `VersionIsReleased`, `VersionIsKept`; integration for `kept` with a firmware in the
  trash.
- bootstrap: `AttachmentSubjects` for a version; the migration up and down.
- The command: the flow against a fake `Api` and compiler; `flash_args` parsing; the `urllib`
  client against a local HTTP server; an integration run through the real app with a fake
  compiler.
- Web: `bundle.ts` on zips made in the test and on the Python fixture; the dialog with and
  without a stored build; `BuildsSection`.
- E2E: attach a build to a released version, see it listed and offered by the dialog.

## Seams for later specs

- A build made by PlatformIO or ESP-IDF needs only another compiler behind the command; the
  manifest already carries the tool's name.
- Checking a build against its source (a hash of the files in the manifest) fits `format: 2`.
