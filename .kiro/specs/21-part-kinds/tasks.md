# Implementation Plan

## Overview

Six tasks that build [design.md](design.md) against [requirements.md](requirements.md). One
migration, `0025`. One task, one commit, each passing `make check` on its own; `make client` on
the tasks that change the wire, the regenerated client in the same commit.

Branch: `feat/part-kinds`, from `main`.

## Tasks

- [x] 1. Catalog: a category's kind
  - The flag, its resolution, `SetCategoryKind`, migration `0025`, the wire and the client.
  - `feat(catalog): let a category say its parts are mechanical`
  - _Requirements: 1.1, 1.2, 1.5_

- [x] 2. Catalog: no pinout for a mechanical part, and none left behind
  - `turning.py`; `refuse_unfit_mechanical` for pinouts on the three writes; `ReplacePinout`.
  - `feat(catalog): keep pinouts to electronic parts`
  - _Requirements: 1.3, 1.4, 2.2_

- [x] 3. Projects: wiring is for electronic parts
  - `PartFacts.mechanical`, the net refusal, `WiredParts`, `PartUses.wired`, the guard's second
    half.
  - `feat(projects): keep wiring to electronic parts`
  - _Requirements: 1.3, 2.1_

- [x] 4. Catalog: find parts by kind
  - `PartQuery.mechanical`, the search spec, the wire and the client.
  - `feat(catalog): list and search parts by kind`
  - _Requirements: 3.1, 3.2_

- [x] 5. Web: the kind everywhere it shows
  - The category control, the part page and form, the filter, the BOM row; the journey.
  - `feat(web): follow a part's kind on its page, its form, the lists and the BOM`
  - _Requirements: 1.1, 1.2, 2.3, 2.4, 3.1, 4.1, 4.2_

- [x] 6. Documents
  - ADR 0005, the architecture document and the README, with their twins.
  - `docs: describe part kinds`
