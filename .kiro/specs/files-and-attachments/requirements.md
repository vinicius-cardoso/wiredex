# Requirements Document

## Introduction

Files and attachments, the third of four specs in `v0.3.0`: datasheets, images and pinout
diagrams attached to part definitions, stored in OCI Object Storage. It creates the `files`
module that [docs/architecture.md](../../../docs/architecture.md) plans ("Attachment,
content-addressed by SHA-256; the same bytes are stored once"), which projects will reuse
for build photos in `v0.5.0`. The requirements were written against [design.md](design.md),
which came first (Design-First).

Acceptance criteria use EARS: `WHEN <condition> THE SYSTEM SHALL <behaviour>`. Every
criterion acts inside the caller's workspace.

## Glossary

- **The owner**: the single real user. A guest acts the same way inside their demo bench.
- **File**: stored bytes, identified by their SHA-256 within a workspace. The same bytes
  uploaded twice are one file.
- **Attachment**: a file attached to a subject (a part definition, for now), with a kind
  and a title. Two parts can attach the same file.
- **Subject**: what an attachment belongs to: `part:<id>` now, `project:<id>` later.
- **Kind**: `datasheet`, `image`, `pinout_diagram` or `other`.
- **File store**: where the bytes live: OCI Object Storage in production, a local folder in
  development and tests.
- **Quota**: the most bytes a workspace may store.

## Requirements

### Requirement 1: Attaching a file to a part

**User Story:** As the owner, I want to attach a part's datasheet and pictures to it, so that
I never search the web again for the PDF of a part I already own.

#### Acceptance Criteria

1. WHEN a file is uploaded to a part with a kind and an optional title THE SYSTEM SHALL
   store it and answer with the attachment: id, kind, title, media type, size and the time
   it was attached.
2. WHEN no title is given THE SYSTEM SHALL use the uploaded file's name, trimmed and capped
   at 120 characters.
3. WHEN the same bytes are already stored in the workspace THE SYSTEM SHALL reuse them and
   not store a second copy.
4. WHEN the same file is attached twice to the same part THE SYSTEM SHALL refuse it with
   409.
5. WHEN a file is attached to a part that doesn't exist or is in another workspace THE
   SYSTEM SHALL answer 404 and store nothing.
6. WHEN the attachments of a part are requested THE SYSTEM SHALL return them newest first.

### Requirement 2: What may be uploaded

**User Story:** As the owner, I want uploads limited to documents and pictures, so that the
file store can't be used to serve something harmful from Wiredex's own address.

#### Acceptance Criteria

1. WHEN a file is uploaded THE SYSTEM SHALL decide its type from its first bytes, not from
   its name or the type the browser claims.
2. WHEN the bytes are a PDF, PNG, JPEG or WebP THE SYSTEM SHALL accept them.
3. WHEN the bytes are anything else, SVG and HTML included THE SYSTEM SHALL refuse the
   upload with 415.
4. WHEN a file is larger than 25 MB THE SYSTEM SHALL refuse it with 413, without reading
   more than the limit.
5. WHEN a file is empty THE SYSTEM SHALL refuse it with 422.
6. WHEN an upload would take the workspace past its quota THE SYSTEM SHALL refuse it with
   413 and say how much space is left.
7. WHEN the workspace is a demo bench THE SYSTEM SHALL give it a quota of 25 MB; the owner's
   workspace SHALL get 5 GB.

### Requirement 3: Opening an attachment

**User Story:** As the owner, I want to open a datasheet in the browser from the part page,
so that checking a pin's maximum rating takes one click.

#### Acceptance Criteria

1. WHEN an attachment's content is requested THE SYSTEM SHALL send the bytes with their
   media type and the attachment's title as the file name.
2. WHEN a PDF or an image is opened THE SYSTEM SHALL let the browser show it inline; WHEN
   asked for a download THE SYSTEM SHALL send it as a download.
3. WHEN content is sent THE SYSTEM SHALL mark it cacheable by the browser only (private)
   and for good, since an attachment's bytes never change, and SHALL send
   `X-Content-Type-Options: nosniff`.
4. WHEN the content of an attachment of another workspace is requested THE SYSTEM SHALL
   answer 404.
5. WHEN content is sent THE SYSTEM SHALL stream it, not hold the whole file in memory.

### Requirement 4: Changing and removing attachments

**User Story:** As the owner, I want to rename, re-kind and remove attachments, so that the
part page stays tidy.

#### Acceptance Criteria

1. WHEN an attachment's title or kind is changed THE SYSTEM SHALL store the change and keep
   its file.
2. WHEN an attachment is removed THE SYSTEM SHALL delete it, and delete its file when no
   other attachment in the workspace uses it.
3. WHEN a part is deleted THE SYSTEM SHALL have its attachments go with it, at the latest by
   the next nightly prune.
4. WHEN the nightly prune runs THE SYSTEM SHALL delete attachments whose subject no longer
   exists, file rows no attachment uses, and stored objects no file row names.

### Requirement 5: Workspace isolation

**User Story:** As the owner, I want attachments to be as private as the parts they belong
to, so that lending a demo account stays safe.

#### Acceptance Criteria

1. WHEN the application connects as its non-owner database role THE SYSTEM SHALL have
   row-level security deny reads and writes of another workspace's files and attachments.
2. WHEN bytes are stored THE SYSTEM SHALL keep them under the workspace's own prefix in the
   file store, so two workspaces never share an object.
3. WHEN a guest's demo bench is reset THE SYSTEM SHALL delete every attachment, file row
   and stored object of that workspace.
4. WHEN the file store is reached THE SYSTEM SHALL use a key that can only read and write
   the files bucket, and nothing else in the cloud account.

### Requirement 6: Web

**User Story:** As the owner, I want an attachments section on the part page, so that
adding a datasheet is a drag and drop.

#### Acceptance Criteria

1. WHEN a part page loads THE SYSTEM SHALL list its attachments with kind, title, size and
   date, images shown as small previews.
2. WHEN a file is dropped on the section or picked with the file button THE SYSTEM SHALL
   upload it, with a kind guessed from its type (PDF → datasheet, image → image) that can be
   changed before or after.
3. WHEN an upload is refused THE SYSTEM SHALL say why in the words of the refusal (too
   large, not a PDF or picture, quota reached, already attached) and keep the page as it
   was.
4. WHEN an attachment is opened THE SYSTEM SHALL open it in a new tab; a download action
   SHALL download it.
5. WHEN an attachment is removed THE SYSTEM SHALL ask first.
6. WHEN any attachment screen is rendered THE SYSTEM SHALL take every string from an i18n key
   in both `en.json` and `pt-BR.json`, every colour from a theme token, and be usable by
   keyboard, drop zone included.

### Requirement 7: Operations and non-functional

**User Story:** As the owner, I want file storage that is free, backed up and hard to break,
so that the small server stays healthy.

#### Acceptance Criteria

1. WHEN the API starts in production without file-store settings THE SYSTEM SHALL refuse to
   start, so a deploy fails and rolls back instead of breaking uploads silently.
2. WHEN files are stored in production THE SYSTEM SHALL keep them in a private bucket with
   object versioning, whose previous versions are deleted after 30 days, so a deleted file
   can be recovered for a month.
3. WHEN a request to the file store is made THE SYSTEM SHALL not block the event loop.
4. WHEN migration `0007` is applied THE SYSTEM SHALL be reversible, and the up → down → up
   round trip SHALL pass.
5. WHEN routes or schemas change THE SYSTEM SHALL have `packages/api-client` regenerated.
6. WHEN the test suites run THE SYSTEM SHALL keep API coverage at or above 90 % and web
   coverage at or above 85 %, and every commit SHALL pass `make check` on its own.
