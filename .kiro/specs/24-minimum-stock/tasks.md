# Implementation Plan

## Overview

Three tasks that build [design.md](design.md) against [requirements.md](requirements.md). One
migration, `0028`. One task, one commit, each passing `make check` on its own; the regenerated
client rides with the API task.

Branch: `feat/minimum-stock`, from `main`.

## Tasks

- [x] 1. API: minimums, the reorder list and the workspace's settings
  - Catalog's two columns and list, the `preferences` module, migration `0028`, the wire and
    the client. _Requirements: 1, 2, 3, 4, 6_
- [x] 2. Web: Settings, Reorder, and the minimum on parts and categories
  - Both languages, the navigation, the menu, the palette, the dashboard and the journey.
    _Requirements: 5_
- [x] 3. Docs
  - The README's feature row, layout and roadmap line, in both languages.
