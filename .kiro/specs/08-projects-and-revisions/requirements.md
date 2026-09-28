# Requirements Document

## Introduction

Projects and revisions, the first of three specs in `v0.5.0` Projects & BOM. It delivers two
of the phase's roadmap lines: *projects with description, tags and photos*, and *revisions,
including forking from an existing revision*. It creates the `projects` module that
[docs/architecture.md](../../../docs/architecture.md) §2 and §3 plan, and builds what
[ADR 0003](../../../docs/adr/0003-project-revisions.md) decided: a project holds identity,
description, tags and photos; a revision (`A – breadboard`, `B – perfboard`) holds the bill of
materials, the netlist and the firmware line; the latest revision opens by default; and a new
revision can be forked from an existing one.

The next two specs build on it. [09-bill-of-materials](../09-bill-of-materials/design.md)
gives a revision its BOM lines and the shortage report, and
[10-build-lifecycle](../10-build-lifecycle/design.md) moves a revision through `Draft →
Reserved → Built → Dismantled` with its stock effects and closes the phase. This spec stores a revision's
status from the start, always `draft`, and leaves every transition to 10. Photos and a
revision's files reuse the `files` module ([ADR 0013](../../../docs/adr/0013-file-storage.md)),
which docs/architecture.md §10 question 4 already points at for build photos and Gerbers in
`v0.5.0`. Requirements-first: [design.md](design.md) answers these.

Acceptance criteria use EARS: `WHEN <condition> THE SYSTEM SHALL <behaviour>`. Every criterion
acts inside the caller's workspace.

Owner decisions (2026-09-27) that bind every spec and reach this one: one PR per spec with
auto-merge, and the release PR waits for the phase's last spec (10-build-lifecycle), which only
the owner merges. This spec is the phase's first, so it carries no `Release-As` footer. A BOM
line names exactly one part definition, and consumables use a "not stocked" category flag;
both are 09's to build, and a fork copies whatever 09 stores (Requirement 6).

## Glossary

- **The owner**: the single real user. A guest acts the same way inside their demo bench.
- **Project**: something being built — a weather station, a greenhouse controller — with a
  name, a description, tags and photos (ADR 0003).
- **Revision**: one stage of a project — breadboard, perfboard, PCB — named by a label and a
  summary, as in `A – breadboard`. It will hold the BOM (09-bill-of-materials), the netlist
  (11-netlist-editor) and the firmware line (13-firmware-versions).
- **Label**: a revision's short name within its project: `A`, `B`, `v2`, `1.1`. Two revisions
  of one project never share one, ignoring case.
- **Summary**: a few words on what a revision is: *breadboard*, *first PCB*.
- **Suggested label**: the label a new revision takes when none is typed (Requirement 4.4).
- **Latest revision**: the project's revision created last, the one a project opens on.
- **Fork**: a new draft revision started from an existing revision of the same project,
  carrying the source's content.
- **Revision content**: a kind of thing a revision holds that a fork copies, such as 09's BOM
  lines or 11's nets. This spec defines the way contents register and defines none itself.
- **Status**: where a revision stands in its build lifecycle: `draft`, `reserved`, `built` or
  `dismantled` (ADR 0003). The transitions belong to 10-build-lifecycle; this spec stores
  `draft`.
- **Tag**: a word a project is filed under, normalized as Requirement 2.1 says.
- **Last activity**: when a project or any of its revisions last changed (Requirement 3.2).
- **Photo**: an image attached to a project.
- **Revision file**: a file attached to a revision: a schematic, a Gerber archive, a photo of
  the build.
- **Subject**: what the `files` module attaches a file to: `part:<id>` until now, and from this
  spec `project:<id>` and `revision:<id>`.

## Requirements

### Requirement 1: Projects

**User Story:** As the owner, I want each project described once, with a name, a description
and tags, so that everything I build has one place I can find again.

#### Acceptance Criteria

1. WHEN a project is created with a name, and optionally a description and tags, THE SYSTEM
   SHALL store it together with a first revision labelled `A`, in one transaction.
2. WHEN a project's name is given THE SYSTEM SHALL trim it and collapse its inner whitespace,
   and refuse with 422 a name that is then empty or longer than 120 characters.
3. WHEN a project is created or renamed with a name another project of the workspace holds,
   ignoring case, THE SYSTEM SHALL answer 409 and name that project.
4. WHEN a project's description is given THE SYSTEM SHALL keep its line breaks, trim its ends,
   read a blank description as none, and refuse one longer than 4,000 characters with 422.
5. WHEN a project is edited THE SYSTEM SHALL replace its name, description and tags with the
   edit's, and write nothing when they are the ones it already has.
6. WHEN a project is opened THE SYSTEM SHALL answer its name, description and tags, its
   revisions oldest first, which of them is the latest, and the label a new revision would be
   suggested.
7. WHEN a project is deleted THE SYSTEM SHALL delete it and all its revisions in one
   transaction.
8. WHEN a project holding a revision that is not a draft is deleted THE SYSTEM SHALL refuse it
   with 409 and delete nothing.
9. WHEN a project that is not in the workspace is opened, edited or deleted THE SYSTEM SHALL
   answer 404.

### Requirement 2: Tags

**User Story:** As the owner, I want to file projects under a few tags, so that every ESP32 or
I²C project comes up at once.

#### Acceptance Criteria

1. WHEN a tag is given THE SYSTEM SHALL normalize it — Unicode NFKC, trimmed, inner whitespace
   collapsed to one space, lower-cased — so `ESP32` and ` esp32 ` are one tag.
2. WHEN a tag is empty after normalizing, longer than 32 characters, or holds a comma or a
   control character THE SYSTEM SHALL refuse it with 422 and name it.
3. WHEN a project's tags are stored THE SYSTEM SHALL keep each tag once, in alphabetical order,
   whatever order and repetition they were given in.
4. WHEN more than 20 distinct tags are given for one project THE SYSTEM SHALL refuse them with
   422.
5. WHEN a project's stored tags are given back unchanged THE SYSTEM SHALL store the same tags.
6. WHEN the workspace's tags are requested THE SYSTEM SHALL answer each tag its projects carry
   once, with the number of projects carrying it, in alphabetical order.

### Requirement 3: Finding projects

**User Story:** As the owner, I want the project list to open on what I worked on last and to
narrow by name or tag, so that getting back to a build takes seconds.

#### Acceptance Criteria

1. WHEN the project list is requested THE SYSTEM SHALL answer each project of the workspace
   with its tags, its number of revisions, its latest revision's label, summary and status, and
   its last activity.
2. WHEN the project list is answered THE SYSTEM SHALL order it by last activity, newest first,
   a project's last activity being the latest of when its details changed and when any of its
   revisions was added, forked, edited or deleted.
3. WHEN the list is narrowed by text THE SYSTEM SHALL keep the projects whose name contains
   the text, ignoring case, with `%` and `_` matching only themselves.
4. WHEN the list is narrowed by tags THE SYSTEM SHALL keep the projects carrying every one of
   them, each normalized as a stored tag is.
5. WHEN no project matches THE SYSTEM SHALL answer an empty list with 200.

### Requirement 4: Revisions and their labels

**User Story:** As the owner, I want each stage of a project — breadboard, perfboard, PCB —
kept as a revision of its own, so that how the last one was built survives the next.

#### Acceptance Criteria

1. WHEN a revision is added to a project THE SYSTEM SHALL create it as a draft, with the label
   given or else the suggested one, and with the summary and notes given.
2. WHEN a label is given THE SYSTEM SHALL accept 1 to 16 ASCII letters, digits, `.`, `-` and
   `_` that start and end with a letter or a digit, and refuse any other with 422.
3. WHEN a revision is added, forked or relabelled with a label another revision of the same
   project holds, ignoring case, THE SYSTEM SHALL answer 409.
4. WHEN a label is suggested for a project with revisions THE SYSTEM SHALL step the latest
   revision's label, its trailing number up by one (`v2` → `v3`, `1.9` → `1.10`) or else its
   trailing letters to the next in spreadsheet-column order (`A` → `B`, `Z` → `AA`), until it
   reaches a label no revision of the project holds.
5. WHEN a label is suggested for a project with no revision THE SYSTEM SHALL suggest `A`.
6. WHEN a revision is added or forked without a label and no label of at most 16 characters
   can be suggested THE SYSTEM SHALL refuse it with 422 and ask for one.
7. WHEN a revision's summary is given THE SYSTEM SHALL trim it and collapse its whitespace, and
   refuse with 422 one that is then empty or longer than 120 characters; its notes follow a
   project description's rules.
8. WHEN a revision is edited THE SYSTEM SHALL replace its label, summary and notes with the
   edit's, whatever its status, and write nothing when they are the ones it already has.
9. WHEN a revision is stored THE SYSTEM SHALL store its status, accepting only `draft`,
   `reserved`, `built` and `dismantled`, and every revision this spec creates SHALL be a draft.
10. WHEN a project's latest revision is named THE SYSTEM SHALL name the revision of that
    project created last.

### Requirement 5: Removing a revision

**User Story:** As the owner, I want to remove a revision I started by mistake, so that the
list of stages stays true to what I built.

#### Acceptance Criteria

1. WHEN a draft revision of a project with other revisions is deleted THE SYSTEM SHALL delete
   it.
2. WHEN a project's only revision is deleted THE SYSTEM SHALL refuse it with 409 and keep it.
3. WHEN a revision that is not a draft is deleted THE SYSTEM SHALL refuse it with 409 and keep
   it.
4. WHEN a revision that other revisions were forked from is deleted THE SYSTEM SHALL keep those
   revisions and clear where they were forked from.
5. WHEN revisions of one project are added, forked, relabelled or deleted by concurrent
   requests THE SYSTEM SHALL apply them one at a time, so labels stay distinct and the project
   keeps at least one revision.
6. WHEN a revision that is not in the workspace is edited, forked or deleted THE SYSTEM SHALL
   answer 404.

### Requirement 6: Forking

**User Story:** As the owner, I want to start a revision from the one before it, so that the
perfboard begins with everything the breadboard had while the breadboard stays as it was
built.

#### Acceptance Criteria

1. WHEN a revision is forked THE SYSTEM SHALL create a draft revision in the same project,
   labelled as given or else as suggested, with the summary and notes given, and record the
   revision it was forked from.
2. WHEN a revision is forked THE SYSTEM SHALL copy every kind of revision content registered
   with the projects module from the source into the fork, one kind after another in the order
   they were registered, in the same transaction as the fork.
3. WHEN a revision is forked THE SYSTEM SHALL leave the source revision, its content and the
   project's other revisions unchanged.
4. WHEN any step of a fork fails THE SYSTEM SHALL write nothing: no revision and no copied
   content.
5. WHEN a revision is forked THE SYSTEM SHALL fork it whatever its status.
6. WHEN a revision is forked THE SYSTEM SHALL attach none of the source's files to the fork.
7. WHEN a later spec gives revisions a new kind of content THE SYSTEM SHALL copy it on every
   fork once that kind is registered with the projects' unit of work, with the fork use case
   unchanged.

### Requirement 7: Photos and files

**User Story:** As the owner, I want photos on a project and the build's files on each
revision, so that how it looks and what went to the fab sit next to the design.

#### Acceptance Criteria

1. WHEN a file is uploaded to a project THE SYSTEM SHALL attach it as one of the project's
   photos when its bytes are a PNG, JPEG or WebP image, and refuse any other file with 415.
2. WHEN a file is uploaded to a revision THE SYSTEM SHALL attach it when its bytes are a PDF, a
   PNG, JPEG or WebP image, or a ZIP archive, and refuse any other file with 415.
3. WHEN an upload to a part or a revision begins with a ZIP local file header THE SYSTEM SHALL
   read it as a ZIP archive, whatever its name or claimed type.
4. WHEN a ZIP archive's content is requested THE SYSTEM SHALL send it as a download with its own
   media type and `nosniff`, including when the request does not ask for a download.
5. WHEN a file is attached THE SYSTEM SHALL accept the kinds schematic and Gerbers besides
   datasheet, image, pinout diagram and other.
6. WHEN a file is uploaded to a project or a revision that is not in the workspace THE SYSTEM
   SHALL answer 404 and store nothing.
7. WHEN a project's photos or a revision's files are listed, opened, renamed or removed THE
   SYSTEM SHALL treat them as it treats a part's attachments: the same bytes stored once per
   workspace, counted against the workspace's quota, listed newest first.
8. WHEN the nightly prune runs after a project or a revision was deleted THE SYSTEM SHALL
   remove that project's or revision's attachments, as it removes a deleted part's.

### Requirement 8: Workspace isolation

**User Story:** As the owner, I want a guest's projects kept inside their bench, so that lending
a demo account stays safe.

#### Acceptance Criteria

1. WHEN the application connects as its non-owner database role THE SYSTEM SHALL have
   row-level security deny reads and writes of another workspace's projects and revisions.
2. WHEN a project or revision of another workspace is named by id THE SYSTEM SHALL answer 404,
   not 403.
3. WHEN the project list or the tag list is requested THE SYSTEM SHALL include no other
   workspace's projects or tags.
4. WHEN a revision is written THE SYSTEM SHALL have the database refuse it unless its project
   belongs to the same workspace.
5. WHEN a projects request carries no valid session THE SYSTEM SHALL answer 401 and touch
   nothing.
6. WHEN a projects write carries no CSRF header THE SYSTEM SHALL answer 403 and touch nothing.

### Requirement 9: The demo workspace

**User Story:** As the owner, I want a guest's bench to open with sample projects, so that a
demo shows what projects and revisions are for.

#### Acceptance Criteria

1. WHEN a guest's demo workspace is reset THE SYSTEM SHALL restore its sample projects, each
   with its description, tags and revisions and one revision forked from another, after its
   sample catalog and inventory.
2. WHEN a demo reset runs again THE SYSTEM SHALL remove the projects a guest added and put the
   sample projects back as they were.
3. WHEN a demo reset runs THE SYSTEM SHALL restore sample projects in demo workspaces only.
4. WHEN a guest is invited THE SYSTEM SHALL seed the new bench with the same sample catalog,
   inventory and projects the nightly reset restores.

### Requirement 10: Web

**User Story:** As the owner, I want projects and revisions in the browser, so that planning
the next build happens where I keep my parts.

#### Acceptance Criteria

1. WHEN the signed-in app is shown THE SYSTEM SHALL offer *Projects* in the main navigation.
2. WHEN the projects page is opened THE SYSTEM SHALL list the projects with their tags, latest
   revision and last activity, and let the list be narrowed by a search box and by tags, both
   kept in the address.
3. WHEN a new project is saved THE SYSTEM SHALL open its page on revision `A`.
4. WHEN a project page is opened without naming a revision THE SYSTEM SHALL open the latest
   revision, and list every revision of the project, each reachable by a link, with the open
   one marked.
5. WHEN a revision is shown THE SYSTEM SHALL show its label, summary, status, notes, the
   revision it was forked from and its files, and offer to edit, fork and delete it, with
   deleting unavailable, and saying why, for a project's only revision.
6. WHEN a revision is added or forked in the browser THE SYSTEM SHALL offer the suggested
   label, take a summary and notes, and open the new revision.
7. WHEN tags are typed THE SYSTEM SHALL add a tag on Enter or a comma, suggest the workspace's
   tags, and let each tag be removed by keyboard.
8. WHEN a project's photos are shown THE SYSTEM SHALL show them as a gallery, each image's text
   alternative its title, and let photos be added, renamed and removed.
9. WHEN a file is chosen for a revision THE SYSTEM SHALL suggest the kind schematic for a PDF,
   Gerbers for a ZIP archive and image for a picture, changeable before the upload.
10. WHEN a project, revision, photo or file changes THE SYSTEM SHALL refresh the affected list
    and page in place, without a full reload.
11. WHEN any projects screen is rendered THE SYSTEM SHALL take every string from an i18n key
    present in both `en.json` and `pt-BR.json`, and every colour from a theme token.
12. WHEN those screens are operated by keyboard alone THE SYSTEM SHALL expose every control with
    a role and an accessible name.

### Requirement 11: Non-functional

**User Story:** As the owner, I want projects to keep the architecture's lines, so that the
next three phases build on them without rework.

#### Acceptance Criteria

1. WHEN the API is linted THE SYSTEM SHALL satisfy the import-linter contracts with `projects`
   as a module of its own: its domain imports no framework, its layers point inward, it imports
   no other module, and only the composition root connects it to `files`.
2. WHEN migrations `0013`, `0014` and `0015` are applied THE SYSTEM SHALL only add tables and
   widen CHECK constraints, and each SHALL pass the up → down → up round trip.
3. WHEN a project page or the project list is read THE SYSTEM SHALL use a fixed number of
   queries, whatever the number of projects and revisions.
4. WHEN routes or schemas change THE SYSTEM SHALL have `packages/api-client` regenerated, so
   CI's contract gate passes.
5. WHEN the API test suite runs THE SYSTEM SHALL keep total coverage at or above 90 %, and the
   web suite at or above 85 %.
6. WHEN the label rules, tag normalization, the revision invariants and the fork are tested THE
   SYSTEM SHALL check them with Hypothesis.
