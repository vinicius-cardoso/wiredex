# Implementation Plan

## Overview

Three tasks that build [design.md](design.md) against [requirements.md](requirements.md). No
migration. One task, one commit, each passing `make check` on its own.

Branch: `feat/change-password`, from `main`.

## Tasks

- [x] 1. API: change your own password
  - The rules, `ChangePassword`, the throttle's third key, the route and the client.
    _Requirements: 1, 2_
- [x] 2. Web: the form on the devices page
  - Both languages, the menu item, and the journey. _Requirements: 3_
- [x] 3. Docs
  - ADR 0008 and the README's security list, in both languages.
