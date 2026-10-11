# Implementation Plan

## Overview

Three tasks that build [design.md](design.md) against [requirements.md](requirements.md). One
migration, `0027`. One task, one commit, each passing `make check` on its own; the regenerated
client rides with the API task.

Branch: `feat/firmware-git-link`, from `main`.

## Tasks

- [x] 1. API: a firmware's repository and a version's commit
  - The two values, their refusals, `LinkCommit`, migration `0027`, the wire, history's
    restore, and the client. _Requirements: 1, 2, 4.2, 5_
- [x] 2. Web: the form field, the repository link and the commit control
  - Both languages, history's labels, and the firmware journey. _Requirements: 3, 4.1_
- [x] 3. Docs
  - ADR 0006, the README's feature row and roadmap line, in both languages.
