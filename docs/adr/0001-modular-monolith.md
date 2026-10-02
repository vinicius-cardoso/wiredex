# 0001. Build a modular monolith with hexagonal modules

- **Status:** Accepted
- **Date:** 2026-09-22

## Context

Wiredex has one user and a host with less than 1 GB of RAM, but the domain has
real boundaries: catalog, inventory, projects, firmware, identity. Microservices
would add network hops, deployments and failure modes and give nothing back.
One big layer-by-type app (`models/`, `routes/`, `services/`) would let those
boundaries rot.

## Decision

- One deployable FastAPI process, split into **modules per bounded context**:
  `identity`, `catalog`, `inventory`, `projects`, `firmware`, `files`, plus a
  small `shared_kernel`.
- Inside each module, **ports and adapters** layers:
  `domain` (pure Python, no framework imports) → `application` (use cases,
  ports) → `infrastructure` (SQLAlchemy, storage) and `api` (FastAPI routers,
  schemas).
- Modules talk to each other only through a published **facade** (an
  application-level interface), never through each other's tables or ORM
  models.
- Boundaries are enforced in CI with **import-linter** contracts.

## Implementation (v0.4)

- The "facade" is a **port the consumer declares** and `bootstrap/` implements. Modules
  never import each other (import-linter's independence contract), so inventory declares
  `Parts` in its own `application/ports.py` and `bootstrap/inventory.py` answers it with
  catalog's `GetPart`.
- A **write into two modules rides the caller's unit of work.** The port is a property of
  that unit of work, not a constructor argument, and bootstrap binds it to the same
  session: `IntakeUnitOfWork.catalog` is a `PartCatalog`, and `SqlIntakeUnitOfWork`
  (`bootstrap/intake.py`) binds `CatalogPartDesk` to inventory's session. One
  `set_config('app.workspace_id', …)` scopes both modules' rows, and one `commit()` keeps
  both, or neither.
- The provider offers **in-transaction operations over a repositories-only protocol**,
  which has no `commit` and so can't end the caller's transaction: catalog's `PartDrafts`
  runs over `CatalogRepositories`. Inside one module the same shape is a `perform` method,
  as `MoveStock.perform` runs inside `MoveUnit` and `ReceiveStock.perform` and
  `ReceiveUnits.perform` inside quick-add and import.
- Quick-add and sheet import (a part and its first stock) use it first. `v0.5.0`'s build
  lifecycle is the second use, over three modules: `bootstrap/build.py` binds inventory's
  `InventoryRepositories` and catalog's `CatalogRepositories` on the session projects' unit of
  work opens, so a transition is one transaction, one workspace setting and one connection
  across the three, and projects imports neither.
- `v0.6.0`'s netlist is the third use: `bootstrap/netlist.py` binds catalog's parts and
  pinouts on the projects session, so a net write checks its references against the BOM it
  read under the project's lock, in the same transaction, and pin usage reads the part, its
  pinout and every net on it in one.
- `v0.7.0`'s firmware makes the fourth to sixth uses. `bootstrap/fork.py` binds firmware's
  repositories on the projects session, so a fork copies the firmware its source runs after the
  BOM and the netlist, in the fork's one transaction: the first content another module keeps
  that 08's revision contents carry. `bootstrap/firmware.py` binds projects' revisions and
  inventory's units on the session firmware's unit of work opens, so a firmware's page reads the
  revisions it runs on in the same transaction, and a flash locks its unit's row, the one
  inventory's retire and delete lock, so they take turns.

## Implementation (v0.8)

`v0.8.0` adds three modules: `trash`, `history` and `search`. Each one works across the other
modules without holding their rules. Each declares the port it asks through, and bootstrap answers
that port with the owning modules' use cases. None of them rides another module's unit of work.
Their reads need no shared transaction, and their writes are each one module's own.

- **`trash`** ([ADR 0014](0014-soft-delete-and-trash.md)) declares `TrashBin`.
  `bootstrap/trash.py` turns the trash use cases of catalog, inventory, projects and firmware
  (list, restore, delete for good, empty) into four bins. The trash merges the bins' pages and
  passes each restore or delete for good to the module that owns the record. Each bin runs in its
  module's own unit of work, one after another, so emptying the trash commits one module at a
  time.
- **`history`** ([ADR 0015](0015-history-by-triggers.md)) reads only its own tables. Postgres
  triggers write them inside every module's transaction. `bootstrap/history.py` answers its
  `Records` port with each module's `get`, so a record shows in history only where its page would
  show it. It answers `VersionRestorers` with each module's own edit, so a restore follows the
  module's rules in the module's transaction. A move to the trash is restored through the trash's
  use case.
- **`search`** declares `SearchSource`. `bootstrap/search.py` binds six sources (parts, units,
  projects, firmware, categories and locations) to each module's `find`. A search asks the
  sources one after another, each in its own transaction.
- 18's dashboard adds no module. Its reads are projects use cases over ports that 09 and 10
  already declared: `PartLookup`, `StockLevels` and `BuildStock`.

## Consequences

- Clear seams: any module could be split out later without rewriting its domain.
- More files and some mapping code between ORM rows and domain objects.
- Cross-module operations that must be atomic (a build that consumes stock)
  run in one database transaction through the facades. This is simpler than
  sagas and correct for a single database.
