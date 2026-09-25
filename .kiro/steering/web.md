---
inclusion: fileMatch
fileMatchPattern: "apps/web/**"
---
# Web

- Features live in `apps/web/src/features/<feature>/`; server data goes through
  TanStack Query hooks, and routes are declared in `src/app/router.tsx`.
- Colours and fonts come from the theme tokens: #[[file:docs/design/visual-identity.md]]
- Every user-facing string is a key in both
  `packages/i18n/src/locales/en.json` and `pt-BR.json`.
- Tests use Vitest + MSW (`src/test/server.ts`); query by role and accessible name.
- Verify with `make check`, and `make e2e` for user journeys.
