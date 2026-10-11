# Implementation Plan

## Overview

Three tasks that build [design.md](design.md) against [requirements.md](requirements.md). One
migration, `0029`. One task, one commit, each passing `make check` on its own.

Branch: `feat/more-settings`, from `main`.

## Tasks

- [x] 1. API: the settings, and the modules that read them
  - The five columns, the default minimum, the code prefix, the purge and its command,
    migration `0029` and the client. _Requirements: 1, 2, 3, 5.1_
- [x] 2. Web: the Settings page's new sections and the formats
  - Both languages, the pages that show a setting, and the journey. _Requirements: 4, 5.3, 6_
- [x] 3. Docs and the nightly service
  - The READMEs, the runbook and `server-setup.sh`. _Requirements: 5.2_
