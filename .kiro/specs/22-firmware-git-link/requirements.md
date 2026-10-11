# Requirements Document

## Introduction

Firmware git link: a firmware says where its code lives, and a version says which commit it was
cut from. Wiredex keeps a snapshot of each version's source (ADR 0006), which answers "what is
on this board"; the repository answers "where do I go to change it", and until now that was a
line in the description.

It builds on [13-firmware-versions](../13-firmware-versions/requirements.md) and
[17-change-history](../17-change-history/requirements.md). [design.md](design.md) answers
these.

Acceptance criteria use EARS: `WHEN <condition> THE SYSTEM SHALL <behaviour>`. Every criterion
acts inside the caller's workspace.

Owner decision (2026-10-10): **link firmware to a git repository and commit** (the roadmap's
line).

Decisions taken without the owner, for the owner to review:

1. **The repository belongs to the firmware and the commit to a version.** One firmware is one
   repository; each version is one point in its history.
2. **Links only.** Wiredex stores an address and an object name. It never contacts the
   repository: nothing is cloned, fetched or verified, so no token is needed and a private
   repository works as well as a public one.
3. **A released version takes a commit too.** A release's number, changelog and files never
   change; the commit points at the code and isn't part of it, and versions released before
   this feature have to be able to gain one.
4. **A commit is an object name, not a branch or a tag**, since those move.
5. **An address carrying a user name or a token is refused**, never stored: it would sit in the
   database, the change history and every page that links to it.

## Requirements

### Requirement 1: a firmware's repository

1. WHEN a firmware is created or edited with a repository THE SYSTEM SHALL keep it as the
   address of the repository's page: `http` or `https`, the host lower-cased, and no trailing
   slash or `.git`.
2. WHEN the repository is typed as `git@host:owner/repo.git` THE SYSTEM SHALL keep
   `https://host/owner/repo`.
3. WHEN the repository is blank or absent THE SYSTEM SHALL keep none, and an edit that sends
   none SHALL clear the one stored.
4. WHEN the address has no `http(s)` scheme, no host, no path after the host, a query or a
   fragment, or more than 500 characters THE SYSTEM SHALL refuse it with 422
   `invalid_repository` on the field `repository`, and change nothing.
5. WHEN the address carries a user name or a password THE SYSTEM SHALL refuse it the same way,
   with a message that says to remove what comes before the `@`.

### Requirement 2: a version's commit

1. WHEN a commit of 7 to 64 hexadecimal digits is given for a version THE SYSTEM SHALL keep it
   lower-cased, whole or abbreviated as given, whether the version is a draft or released.
2. WHEN the commit is blank or null THE SYSTEM SHALL clear the one stored.
3. WHEN the commit is anything else, a branch or a tag included, THE SYSTEM SHALL refuse it
   with 422 `invalid_commit` on the field `commit`, and change nothing.
4. WHEN the commit given is the one stored THE SYSTEM SHALL write nothing.
5. WHEN a commit changes THE SYSTEM SHALL move the version's and the firmware's last change.
6. WHEN a version is started from another THE SYSTEM SHALL NOT copy that version's commit.

### Requirement 3: the pages

1. WHEN a firmware has a repository THE SYSTEM SHALL show it on the firmware's page as a link
   that opens in a new tab, named without its scheme.
2. THE firmware form SHALL offer the repository as an optional field, with a hint saying what
   to type, and SHALL show a refusal on that field in the reader's language.
3. THE version panel SHALL show the commit's first seven digits, as a link to the commit in the
   repository when the firmware has one and as text otherwise, or say that none is linked.
4. THE version panel SHALL offer to link, change or clear the commit in place, for a draft and
   a release alike, and SHALL show a refusal under the field, keeping what was typed.
5. Every new string SHALL exist in English and Brazilian Portuguese.

### Requirement 4: history

1. WHEN a firmware's repository or a version's commit changes THE SYSTEM SHALL record it in the
   change history as it records the other fields, each named in both languages.
2. WHEN a change to a firmware is restored THE SYSTEM SHALL put its repository back with its
   other details.

### Requirement 5: the release before this one

1. THE migration SHALL only add nullable columns, so the previous release runs against the new
   schema, and its `downgrade` SHALL drop them.
