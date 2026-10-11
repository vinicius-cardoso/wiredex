# Design Document: firmware git link

## Overview

Two optional values and the places that show them: `Repository` on a firmware and `Commit` on a
version. Answers [requirements.md](requirements.md). Nothing reaches out to git: both are text
the owner types, checked for shape.

## Architecture

All of it sits inside the `firmware` module; `history` learns one more restorable field, and
bootstrap builds it. No new port and no new dependency.

## Components and Interfaces

### firmware, domain

- `values.Repository`: the address normalized as requirement 1 says. An scp-like address is
  rewritten to `https://` first, then one pattern reads scheme, host and path. A host holding
  an `@` is the credentials case and gets its own message. `InvalidRepositoryError`.
- `values.Commit`: trimmed, lower-cased, 7 to 64 of `0-9a-f`. `InvalidCommitError`.
- `FirmwareDetails.repository`, so creating, editing and restoring carry it and `revise` sees a
  changed repository as a change.
- `FirmwareVersion.commit` and `link_commit(commit, now) -> bool`, which doesn't ask
  `ensure_editable` (decision 3). `draft` leaves it empty (requirement 2.6).

### firmware, application and API

- `LinkCommit(workspace_id, version_id, commit)`: under the firmware's lock, as every version
  write is; commits and touches the firmware only when something changed.
- `PUT /api/firmware/versions/{version_id}/commit` with `{commit}`, answering the version. Its
  own route rather than a field of `PATCH /versions/{id}`, which a released version refuses
  whole.
- `repository` joins `FirmwareRequest` and `FirmwareResponse`, `commit` joins
  `FirmwareVersionResponse`, and the two codes and fields join the refusal literals.

### Persistence

- Migration `0027`: `firmware.repository varchar(500) NULL` and
  `firmware_versions.commit_sha varchar(64) NULL`. The column isn't `commit`, a word of SQL;
  the mapper names the attribute `commit`, as it names `version` `number`.
- History's triggers record whole rows, so both columns are recorded with no change there.
  `EDITABLE_FIELDS[FIRMWARE]` gains `repository`.

### Web

- `FirmwareForm`: a `url` field with a hint. The form checks only the length; what an address
  must look like is the API's to say, so the rule lives in one place.
- `FirmwarePage`: a Repository row in About, shown only when there is one.
- `VersionCommit`: the commit in the version's facts, with a button that opens one field.
  `git.ts` builds the commit's address: `/commit/<name>`, or `/commits/` on Bitbucket.
- History labels for `repository` and `commit_sha`.

## Error Handling

Both refusals are 422 with a code and a field, as the module's other value refusals are. The
messages say what to type instead: the page's address, without what comes before an `@`; the
digits `git log` prints, not a branch or a tag.

## Testing

Unit tests for both values and the API routes; the repository round trip and the migrations in
the integration suite; Vitest for the form, the page and the commit control; and the firmware
journey links a repository and a commit against the real stack.
