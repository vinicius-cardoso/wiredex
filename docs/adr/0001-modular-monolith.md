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

## Consequences

- Clear seams: any module could be split out later without rewriting its domain.
- More files and some mapping code between ORM rows and domain objects.
- Cross-module operations that must be atomic (a build that consumes stock)
  run in one database transaction through the facades. This is simpler than
  sagas and correct for a single database.
