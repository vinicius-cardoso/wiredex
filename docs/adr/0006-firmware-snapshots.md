# 0006. Firmware as versioned source snapshots and a per-unit flash log

- **Status:** Accepted
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

## Consequences

- Answers "what's running on the greenhouse ESP32?" instantly.
- Source is stored as text in Postgres, capped per version (e.g. 1 MB). Linking
  to git or storing binaries stays possible later.
