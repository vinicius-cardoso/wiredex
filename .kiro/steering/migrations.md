---
inclusion: fileMatch
fileMatchPattern: "apps/api/src/wiredex/migrations/**"
---
# Migrations

Create them with `make migration m="..."`, then review the generated file.

- Expand now, contract in a later release: the previous API version must keep
  working, because a failed deploy rolls back the API but never the schema.
- Never import application code; write types as plain SQLAlchemy types.
- Write a `downgrade()` that works; the migration tests run up, down and up again.

The deploy side: #[[file:deploy/README.md]] (section "Database migrations").
