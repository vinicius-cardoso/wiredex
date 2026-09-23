# 0009. Single-host Docker deployment behind Caddy

- **Status:** Accepted
- **Date:** 2026-09-22

## Context

`vinilabs.cc` already runs on an OCI VM with 2 cores, under 1 GB of RAM, 2 GB
of swap and Caddy with automatic HTTPS. Wiredex should share it.

## Decision

- `wiredex.vinilabs.cc` is a new Caddy block. It serves the **static SPA**
  directly and `reverse_proxy`s `/api/*` to the API container on localhost.
  Same origin means no CORS, and cookies stay simple.
- Docker Compose runs `api` (uvicorn, one worker) and `db` (Postgres 17 tuned
  small). Uploads and backups live on named volumes.
- Images are built in GitHub Actions and pushed to GHCR. **Nothing is built on
  the server.**
- Deploy: pull the image by tag → `alembic upgrade head` → restart → health
  check → roll back to the previous tag on failure.
- Nightly `pg_dump` plus the uploads directory go off-box (restic to OCI Object
  Storage or similar).

Approximate memory budget:

| Process      | RSS target |
| ------------ | ---------- |
| Postgres     | ≤ 180 MB   |
| API          | ≤ 150 MB   |
| Caddy        | ~15 MB     |
| Docker       | ~60 MB     |

## Consequences

- Cheap and simple, with the same Caddy setup as the blog.
- No staging environment. Pre-merge e2e tests and post-deploy smoke tests carry
  that weight.
- The data only survives a lost box if the off-box backups work, so restores
  get tested.
