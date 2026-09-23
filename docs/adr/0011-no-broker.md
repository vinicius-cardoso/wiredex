# 0011. No broker: background work runs as CLI commands on timers

- **Status:** Proposed
- **Date:** 2026-09-22

## Context

Background work is rare and periodic: the nightly demo reset, backups, and
maybe rebuilding thumbnails. Redis plus Celery would cost 100+ MB of RAM the
box doesn't have.

## Decision

- Every job is a **CLI command** (`wiredex demo reset`, `wiredex stock rebuild`)
  and runs from a systemd timer through `docker compose run --rm api …`.
- In-process work that can wait for the response uses FastAPI
  `BackgroundTasks`. Domain events are dispatched in-process after commit.

## Consequences

- No extra services to run or monitor.
- If real queues are ever needed, a Postgres-backed queue
  (`SELECT … FOR UPDATE SKIP LOCKED`) comes before any broker.
