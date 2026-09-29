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

## Consequences

- Clear seams: any module could be split out later without rewriting its domain.
- More files and some mapping code between ORM rows and domain objects.
- Cross-module operations that must be atomic (a build that consumes stock)
  run in one database transaction through the facades. This is simpler than
  sagas and correct for a single database.
