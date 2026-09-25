---
inclusion: fileMatch
fileMatchPattern: "e2e/**"
---
# End-to-end tests

- `tests/auth.setup.ts` logs in once and saves the session that every journey
  reuses. A test that logs out or revokes sessions must log in on its own, with
  `test.use({ storageState: LOGGED_OUT })` and `logIn(page)` from `tests/owner.ts`.
- Use unique names (for example with `Date.now()`) for anything a test creates:
  the local database keeps data between runs.
- Postgres must be running (`make db`).
