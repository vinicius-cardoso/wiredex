# Requirements Document

## Introduction

The dashboard, the third of four specs in `v0.8.0` Everyday use. It delivers the phase's roadmap
line *Dashboard: parts tied up in builds, recent activity, shortages*: the page the app opens on,
which today only says the bench is empty, becomes three panels answering *what is my stock doing,
what changed, and what am I missing*.

It builds on [17-history](../17-history/requirements.md), whose feed is the dashboard's recent
activity, and on what earlier phases already compute: 10-build-lifecycle's holdings, folded from
the ledger, and 09-bill-of-materials's shortage report, whose module docstring has always said the
`v0.8.0` dashboard reads it too. [design.md](design.md) answers these.

Acceptance criteria use EARS: `WHEN <condition> THE SYSTEM SHALL <behaviour>`. Every criterion
acts inside the caller's workspace.

Owner decisions (2026-09-27) that bind every spec and reach this one: one PR per spec with
auto-merge; the release PR waits for the phase's last spec (19-command-palette), and only the owner
merges it, since merging it deploys to production. This spec carries no `Release-As` footer.

Decisions taken without the owner (2026-10-01), for the owner to review:

1. **Three panels, each read on its own: recent activity, parts tied up in builds, and
   shortages.** Recent activity is 17's feed, its newest 10 changes and a link to the whole of
   it; the other two are new reads of the projects module. Why: each panel answers by itself, so
   a slow one never holds the others back, and the feed already exists.
2. **Tied up in builds is what reserved and built revisions hold, per part: how many are
   reserved, how many are in builds, and which revisions hold them.** Why: that is the stock no
   other build can take, and 10's ledger already folds it per revision.
3. **The parts tied up most come first, 20 by default and at most 100, saying how many more
   there are.** Why: every list has a limit, and the biggest holdings are what a person looks
   for.
4. **Shortages are the draft revisions whose BOM is short of a stocked part or names a part the
   catalog no longer holds, each with those parts' need, available stock and shortfall, ordered
   by project and label, 20 at most, saying how many more.** Why: a draft is the next build; a
   reserved or built revision already holds its stock; and it is 09's report, the one each BOM
   page shows, so the two never disagree.
5. **Each draft's shortfall is measured against all the available stock, not shared out between
   drafts.** Why: it matches what the draft's own page says, and sharing the stock out would need
   an order between drafts nobody chose.
6. **A bench with nothing in any panel keeps the invitation it has today.** Why: a new bench still
   learns where to start.

## Glossary

- **The owner**: the single real user. A guest acts the same way inside their demo bench.
- **Holding**: what a reserved or built revision holds of a part: reserved for its build, or
  consumed by it (10-build-lifecycle).
- **Draft**: a revision whose status is draft, in a project that isn't in the trash.
- **Shortfall**: what a draft's BOM needs of a part beyond the part's available stock (09).

## Requirements

### Requirement 1: Parts tied up in builds

**User Story:** As the owner, I want to see what my builds hold, so that I know why stock isn't
free and where it went.

#### Acceptance Criteria

1. WHEN the parts tied up in builds are read THE SYSTEM SHALL answer each part a reserved or built
   revision holds, with its catalog facts or none for a part the catalog no longer holds, how many
   are reserved, how many are in builds, and the revisions holding it, by project name and label.
2. WHEN they are read THE SYSTEM SHALL order them by how many are tied up, most first, then by the
   part's name.
3. WHEN they are read with a limit THE SYSTEM SHALL answer at most that many parts, 20 when none
   is given, refusing a limit below 1 or above 100 with 422, and how many more there are.
4. WHEN a revision is cancelled, built or dismantled THE SYSTEM SHALL answer its holdings as the
   ledger then folds them: nothing for a draft or a dismantled revision.

### Requirement 2: Shortages

**User Story:** As the owner, I want one list of what my next builds are missing, so that I can
buy it in one go.

#### Acceptance Criteria

1. WHEN the shortages are read THE SYSTEM SHALL answer each draft whose BOM is short of a stocked
   part or names an unknown part, with its project's name, its label and summary, its report's
   summary, and the parts short or unknown with their need, available stock and shortfall.
2. WHEN a draft's BOM is covered, holds only consumables, or is empty THE SYSTEM SHALL leave the
   draft out.
3. WHEN they are read THE SYSTEM SHALL order the drafts by project name and label, answer at most
   the limit, 20 when none is given, refusing a limit below 1 or above 100 with 422, and how many
   more there are.
4. WHEN a draft's project is in the trash THE SYSTEM SHALL leave the draft out.

### Requirement 3: Recent activity

**User Story:** As the owner, I want the latest changes on the page I open first, so that I pick
up where I left off.

#### Acceptance Criteria

1. WHEN the dashboard is shown THE SYSTEM SHALL list the workspace's 10 newest changes as 17's feed
   answers them, each with what happened to which record, linking to it, who and when.
2. WHEN the dashboard is shown THE SYSTEM SHALL link to the whole activity.

### Requirement 4: Workspace isolation

**User Story:** As the owner, I want a guest's dashboard kept inside their bench, so that lending a
demo account stays safe.

#### Acceptance Criteria

1. WHEN the holdings or the shortages are read THE SYSTEM SHALL answer only the caller's
   workspace's, row-level security included.
2. WHEN a dashboard request carries no valid session THE SYSTEM SHALL answer 401 and touch nothing.

### Requirement 5: Web

**User Story:** As the owner, I want the dashboard to be the page I check each morning, so that it
reads at a glance.

#### Acceptance Criteria

1. WHEN the dashboard is shown THE SYSTEM SHALL show the three panels, each with its own loading,
   error and empty states, and every part, revision and record linking to its page.
2. WHEN every panel is empty THE SYSTEM SHALL show the invitation a new bench gets today.
3. WHEN a build moves, a BOM changes, stock is received or anything is restored THE SYSTEM SHALL
   show the dashboard as it now stands the next time it is shown, without a full reload.
4. WHEN a dashboard screen is rendered THE SYSTEM SHALL take every string from an i18n key present
   in both `en.json` and `pt-BR.json`, and every colour from a theme token.
5. WHEN it is operated by keyboard alone THE SYSTEM SHALL reach every link, each with an accessible
   name.
6. WHEN it is shown on a phone-width screen THE SYSTEM SHALL keep the page free of horizontal
   scrolling.

### Requirement 6: Non-functional

**User Story:** As the owner, I want the dashboard to stay quick as the bench grows.

#### Acceptance Criteria

1. WHEN the holdings are read THE SYSTEM SHALL use a fixed number of statements, whatever the
   number of revisions, parts and lots.
2. WHEN the shortages are read THE SYSTEM SHALL use a fixed number of statements and
   transactions, whatever the number of drafts and lines, opening each module's transaction only
   after the one before is closed.
3. WHEN the API is linted THE SYSTEM SHALL satisfy the import-linter contracts unchanged.
4. WHEN routes or schemas change THE SYSTEM SHALL have `packages/api-client` regenerated.
5. WHEN the test suites run THE SYSTEM SHALL keep total coverage at or above 90 % for the API and
   85 % for the web.

## Out of scope

- Sharing the available stock out between drafts (decision 5).
- A shopping list across drafts, or ordering from a supplier.
- Configuring which panels show, or their sizes.
- Stock below a threshold: no part carries one yet.
