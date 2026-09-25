---
inclusion: fileMatch
fileMatchPattern: "apps/api/**"
---
# API

The architecture: #[[file:docs/architecture.md]]

- New behaviour starts in the domain (plain Python, no framework imports), then a
  use case in `application/`, then adapters. `make architecture` must pass.
- A table of workspace data needs `workspace_id` and `isolate_by_workspace()` in its
  migration (#[[file:docs/adr/0007-workspace-isolation.md]]).
- Auth follows #[[file:docs/adr/0008-sessions.md]]; never weaken the cookie flags,
  the CSRF check or the login throttle.
- After changing routes or schemas, run `make client`.
- Verify with `make check`, and `make coverage` when SQL code changed.
