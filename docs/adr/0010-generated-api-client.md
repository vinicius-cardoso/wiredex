# 0010. OpenAPI-generated TypeScript client shared by web and mobile

- **Status:** Accepted
- **Date:** 2026-09-22

## Context

FastAPI already publishes an OpenAPI schema. Hand-written fetch calls in React,
and again in React Native, would drift from the backend.

## Decision

- `packages/api-client` is generated from the API's `openapi.json` with
  `openapi-typescript`, and requests go through `openapi-fetch` (small,
  fetch-based, works in React Native).
- The generated output is committed. CI regenerates it and fails on any diff,
  so a backend change that breaks the client fails the PR.

## Consequences

- End-to-end types from Pydantic schemas to React components.
- Backend schema names become part of the public contract, so they need
  deliberate naming.
