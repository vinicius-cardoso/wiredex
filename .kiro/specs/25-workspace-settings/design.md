# Design Document: workspace settings

## Overview

Five columns on `workspace_preferences` and the modules that read them, each through a port
bound in bootstrap, since modules don't import each other. Answers
[requirements.md](requirements.md).

## Components and Interfaces

### preferences

`Choices` holds every setting as one value, checked on construction; `WorkspacePreferences.
choose(choices)` replaces them and says whether anything changed. `PUT /api/preferences` takes
the whole set; what it leaves out takes its default.

### catalog: the default minimum

`ReorderSettingsOf` (was `StockBasisOf`) answers the basis and the default. `minimum_of` takes
the default last; `takes_a_default` says which categories' parts the one read for the reorder
list has to fetch. `GetPart` and `UpdatePart` read the settings before their transaction opens.
Part and reorder answers say `…_from_workspace`.

### inventory: the code prefix

`ShortCode` accepts any prefix a workspace could choose. `CreateLocation` and `ReceiveUnits`
take a `CodePrefixOf` port. `ReceiveUnits.perform`, which quick-add and import call inside their
own transaction, takes the prefix as an argument: each caller asks for it before its
transaction opens, so a receive never holds two connections.

### trash: the retention

Each module's `empty_trash` and empty use case take an optional `before`; `TrashBin.empty`
passes it. `PurgeTrash(days)` empties every bin before now less the days. `wiredex trash prune`
lists every workspace, reads its settings and purges the ones with a retention.

### Web

`useFormats()` in `features/settings/formats.ts` builds the date and number formatters from the
language and the settings; every `Intl.DateTimeFormat` and count formatter goes through it.
The Settings page has four blocks; a typed setting saves on Enter or when left, a choice on
pick. Saves share a mutation scope, so they run in order, and each is built on the last change
rather than on the server's last answer.

## Testing

Unit tests for each rule, the purge and the formatter; Postgres tests for the columns, their
CHECKs, the previous release's insert and the purge; Vitest for each section, the pages that
show a setting, and two quick changes; a journey that changes each setting on a guest's bench.
