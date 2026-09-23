# 0012. SemVer, Conventional Commits and release-please

- **Status:** Accepted
- **Date:** 2026-09-22

## Context

Every change should be traceable to a version, every version documented on
GitHub, and the running version visible in the app.

## Decision

- **Semantic Versioning** for the product: `MAJOR.MINOR.PATCH`. Wiredex stays
  on `0.x` until the MVP (see the README roadmap), and each roadmap phase ships
  as a minor release.
- **Conventional Commits** (`feat:`, `fix:`, `refactor:`, `docs:`, `chore:`,
  `feat!:` / `BREAKING CHANGE:` …), checked in CI on PR titles and commits.
- **release-please** (GitHub Action) keeps a release PR open on `main`.
  Merging it bumps the version, updates `CHANGELOG.md`, tags `vX.Y.Z` and
  publishes a **GitHub Release** with grouped notes.
- Publishing a GitHub Release triggers the production deploy. Images are tagged
  `vX.Y.Z` and `sha-<short>`.
- **GitHub Milestones** mirror the roadmap: one per minor version, and issues
  are filed under the milestone they ship in.
- One version for the whole monorepo (api + web ship together). The mobile app
  can get its own release track later.
- The version is visible at runtime:
  - `GET /api/version` returns `{ version, commit, built_at }`, baked into the
    image at build time.
  - The web build embeds its own version and commit. The app footer (and the
    settings "About" panel) shows `Wiredex v0.4.2 · a1b2c3d`, with a warning
    dot if the web and API versions differ, which means a stale tab after a
    deploy.

## Consequences

- Changelogs write themselves, as long as commit messages are disciplined.
- Deploys happen on purpose (a release) instead of on every push to `main`.
