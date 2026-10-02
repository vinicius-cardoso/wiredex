# Requirements Document

## Introduction

The command palette, the last of four specs in `v0.8.0` Everyday use. It delivers the phase's
roadmap line *Command palette (`Ctrl K`) and global search*: one dialog, opened from any page,
that goes anywhere in the app by typing, either to a page or command, or to a record found by its
name, code or part number.

It searches what the earlier phases and specs keep: parts, categories, locations, units, projects
and firmware, and it never finds what [16-soft-delete-and-trash](../16-soft-delete-and-trash/requirements.md)
put in the trash. It closes the phase: its last task ticks the roadmap's `v0.8.0` lines and
records the phase's decisions in the ADRs. [design.md](design.md) answers these.

Acceptance criteria use EARS: `WHEN <condition> THE SYSTEM SHALL <behaviour>`. Every criterion
acts inside the caller's workspace.

Owner decisions (2026-09-27) that bind every spec and reach this one: one PR per spec with
auto-merge; the release PR waits for the phase's last spec, this one, and only the owner merges
it, since merging it deploys to production. This spec's last commit carries the phase's
`Release-As: 0.8.0` footer (ADR 0012).

Decisions taken without the owner (2026-10-01), for the owner to review:

1. **One dialog holds both halves: commands and the search.** Why: one shortcut to learn, and
   typing a page's name or a part's number goes through the same box.
2. **Six kinds are searched: parts, units, projects, firmware, categories and locations.**
   Revisions, firmware versions, BOM lines, nets, attachments and history are not. Why: these six
   are what the owner names and types; the rest are reached from their record's page.
3. **Each kind matches its identifying text as a case-insensitive substring:** a part's name,
   part number and manufacturer; a unit's code, serial and MAC; a project's name; a firmware's
   name and board target; a category's name; a location's name and code. Why: it is what each
   kind's own list already searches, so a record is found the same way everywhere.
4. **Names that start with the text come first, then the others, each kind by name; five per
   kind, at most 20 when asked, and whether more match.** Why: a palette is for jumping, so the
   closest few matter, and more typing narrows the rest.
5. **A `search` module asks each kind's module in turn, each in its own transaction, never two
   at once.** Why: modules don't import each other (ADR 0001), and the trash already reads
   across modules this way, holding one pooled connection at a time.
6. **No new index.** Why: parts and units, the tables that grow, already have trigram indexes on
   the text searched; projects, firmware, categories and locations hold hundreds of rows on a
   bench.
7. **`Ctrl K`, and `⌘ K` on macOS, opens it from any page, while typing in a field too, but never
   over another dialog.** Why: it is the chord palettes use, it types no character (unlike
   quick-add's `Alt N`), and a modal never stacks on another.
8. **A category opens the parts filed under it; a location opens the locations page with it
   selected.** Why: neither has a page of its own, and those are where each is used.
9. **A kind with more matches says so and asks for more typing; there is no "see all" link.**
   Why: only some list pages hold their search in the address, and one rule reads simpler than
   three.
10. **Commands are a fixed list, filtered in the browser and shown before the records.** Why:
    they are few, need no request, and a typed page name means that page.
11. **The search is asked once typing pauses for 200 ms**, as the part and unit pickers ask.
    Why: one request per word, not per key.

## Glossary

- **The owner**: the single real user. A guest acts the same way inside their demo bench.
- **Palette**: the dialog `Ctrl K` opens, holding a search box and one list of choices.
- **Command**: a choice that opens a page, or quick-add, without naming a record.
- **Hit**: a record the search found, with a title and a detail.

## Requirements

### Requirement 1: Finding records

**User Story:** As the owner, I want to find any part, unit, project, firmware, category or
location by typing a bit of it, so that I don't have to know which page lists it.

#### Acceptance Criteria

1. WHEN the workspace is searched for a text THE SYSTEM SHALL answer, per kind, the records
   whose identifying text contains it, case aside: a part's name, part number or manufacturer; a
   unit's code, serial or MAC; a project's name; a firmware's name or target; a category's name;
   a location's name or code.
2. WHEN hits are answered THE SYSTEM SHALL give each its kind, its id, a title and a detail: a
   part's name with its manufacturer and part number; a unit's code with its part's name; a
   project's name with its tags; a firmware's name with its target; a category's name; a
   location's name with its code.
3. WHEN hits are answered THE SYSTEM SHALL group them by kind, in the order parts, units,
   projects, firmware, categories, locations, leaving out a kind with none, and order each group
   with the records whose title starts with the text first, then by title, case aside.
4. WHEN the workspace is searched with a limit THE SYSTEM SHALL answer at most that many hits
   per kind, five when none is given, refusing a limit below 1 or above 20 with 422, and say for
   each kind whether more match.
5. WHEN the text is blank once trimmed, or longer than 100 characters, THE SYSTEM SHALL refuse
   the search with 422.
6. WHEN the text holds `%`, `_` or `\` THE SYSTEM SHALL match those characters as typed.

### Requirement 2: The trash and other benches

**User Story:** As the owner, I want the search to find only what my bench holds now, so that
what I threw away stays out of my way.

#### Acceptance Criteria

1. WHEN a record is in the trash THE SYSTEM SHALL never answer it as a hit.
2. WHEN the workspace is searched THE SYSTEM SHALL answer only the caller's workspace's records,
   row-level security included.
3. WHEN a search request carries no valid session THE SYSTEM SHALL answer 401 and read nothing.

### Requirement 3: Opening the palette

**User Story:** As the owner, I want the palette one chord away on every page, so that typing is
the quickest way anywhere.

#### Acceptance Criteria

1. WHEN `Ctrl K`, or `⌘ K` on macOS, is pressed on any page while signed in THE SYSTEM SHALL
   open the palette with focus in its search box, unless another dialog is open.
2. WHEN the header's search button is pressed THE SYSTEM SHALL open the palette the same way,
   the button naming its shortcut to assistive technology.
3. WHEN the palette is open THE SYSTEM SHALL keep the page behind it out of reach of the
   keyboard and of assistive technology.
4. WHEN Escape is pressed, or the backdrop is pressed, THE SYSTEM SHALL close the palette and
   put focus back where it was.
5. WHEN nobody is signed in THE SYSTEM SHALL offer no palette.

### Requirement 4: Choosing in the palette

**User Story:** As the owner, I want to reach what I typed with the arrow keys and Enter, so that
my hands never leave the keyboard.

#### Acceptance Criteria

1. WHEN the search box is empty THE SYSTEM SHALL list every command: going to each page of the
   navigation and to the devices page, a new part, a new project, a new firmware, importing from
   a sheet, and quick-add.
2. WHEN text is typed THE SYSTEM SHALL list the commands whose name contains it, case aside,
   then, once typing pauses, the hits, each group under its kind's name, each hit with its title
   and detail.
3. WHEN ArrowDown or ArrowUp is pressed THE SYSTEM SHALL move to the next or previous choice,
   wrapping around, the first choice being the current one once the list changes.
4. WHEN Enter is pressed, or a choice is clicked, THE SYSTEM SHALL close the palette and open the
   choice: a part's, a unit's, a project's or a firmware's own page; for a category, the parts
   filed under it; for a location, the locations page with it selected; for a command, its page
   or quick-add.
5. WHEN a kind has more matches than it shows THE SYSTEM SHALL say so under its group.
6. WHEN the search is asked, fails or finds nothing THE SYSTEM SHALL say so, and announce how many
   choices there are to assistive technology.

### Requirement 5: Web

**User Story:** As the owner, I want the palette to read like the rest of the app, in my language
and on my phone.

#### Acceptance Criteria

1. WHEN the palette is rendered THE SYSTEM SHALL take every string from an i18n key present in
   both `en.json` and `pt-BR.json`, and every colour from a theme token.
2. WHEN it is operated by keyboard alone THE SYSTEM SHALL follow the WAI-ARIA combobox pattern
   with a list popup: the choices a listbox, its groups named, the current choice its active
   descendant.
3. WHEN it is shown on a phone-width screen THE SYSTEM SHALL keep the page free of horizontal
   scrolling.
4. WHEN the locations page is opened with a location named in its address THE SYSTEM SHALL show
   it selected.

### Requirement 6: Non-functional

**User Story:** As the owner, I want the search to stay quick as the bench grows.

#### Acceptance Criteria

1. WHEN the workspace is searched THE SYSTEM SHALL use a fixed number of statements whatever the
   number of records and matches, one module's transaction at a time.
2. WHEN the API is linted THE SYSTEM SHALL satisfy the import-linter contracts, the `search`
   module among the modules that don't import each other.
3. WHEN routes or schemas change THE SYSTEM SHALL have `packages/api-client` regenerated.
4. WHEN the test suites run THE SYSTEM SHALL keep total coverage at or above 90 % for the API and
   85 % for the web.

### Requirement 7: Closing the phase

**User Story:** As the owner, I want the phase's decisions written down where the next phase will
look, so that `v0.8.0` ships whole.

#### Acceptance Criteria

1. WHEN the phase's last commit lands THE SYSTEM SHALL have the roadmap's four `v0.8.0` lines
   ticked, ADRs for the trash and for history, the ADRs and `docs/architecture.md` the phase
   changed updated, and the `Release-As: 0.8.0` footer on a commit that changes something.

## Out of scope

- Searching revisions, versions, BOM lines, nets, attachments' text or history.
- Ranking by use, recent records first, or fuzzy matching of misspellings.
- Commands that write, such as a transition or a move to the trash, from the palette.
- Shortcuts for single commands.
