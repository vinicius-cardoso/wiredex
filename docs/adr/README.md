# Architecture Decision Records

Each file records one decision: the context, the choice, and what it costs.
Records are never edited to change a decision. A new record supersedes the old
one and both link to each other.

**Status legend:** `Accepted` means the owner confirmed it. `Proposed` means it is
recommended and waiting for the system-design pass.

| #    | Decision                                                                 | Status   |
| ---- | ------------------------------------------------------------------------ | -------- |
| 0001 | [Modular monolith with hexagonal modules](0001-modular-monolith.md)      | Accepted |
| 0002 | [Stock as an append-only ledger with reservations](0002-stock-ledger.md) | Accepted |
| 0003 | [BOM, wiring and firmware belong to project revisions](0003-project-revisions.md) | Accepted |
| 0004 | [Wiring as a structured netlist over structured pinouts](0004-netlist-and-pinouts.md) | Accepted |
| 0005 | [Typed part categories with JSONB attribute values](0005-typed-part-attributes.md) | Accepted |
| 0006 | [Firmware as versioned source snapshots and a per-unit flash log](0006-firmware-snapshots.md) | Accepted |
| 0007 | [Workspace isolation with Postgres RLS and a demo workspace](0007-workspace-isolation.md) | Accepted |
| 0008 | [Opaque server-side sessions for web and mobile](0008-sessions.md)       | Proposed |
| 0009 | [Single-host Docker deployment behind Caddy](0009-single-host-deployment.md) | Accepted |
| 0010 | [OpenAPI-generated TypeScript client shared by web and mobile](0010-generated-api-client.md) | Accepted |
| 0011 | [No broker: background work as CLI commands on timers](0011-no-broker.md) | Proposed |
| 0012 | [SemVer, Conventional Commits and release-please](0012-versioning-and-releases.md) | Accepted |

Template: copy [`template.md`](template.md).
