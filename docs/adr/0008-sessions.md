# 0008. Opaque server-side sessions for web and mobile

- **Status:** Accepted
- **Date:** 2026-09-22

## Context

The web app and a future React Native app both need auth, with one to three
users in total. JWTs add key rotation, revocation lists and clock-skew problems
and give nothing back at this scale.

## Decision

- Login returns a random 256-bit **opaque token**. Only its SHA-256 hash is
  stored, in a `sessions` table with an expiry, last-seen time and device
  label.
- The web receives it as a `__Host-` cookie (`HttpOnly`, `Secure`,
  `SameSite=Lax`), and unsafe methods also require a CSRF header. Mobile sends
  it as `Authorization: Bearer`.
- Passwords are hashed with **Argon2id**. Login is rate-limited per IP and per
  account. There is **no public sign-up**: accounts are created with the CLI
  (`wiredex users create`, `wiredex demo invite`).
- Later: TOTP second factor for the owner, and a sessions page to revoke
  devices.

## Consequences

- Revocation is a row delete. There are no refresh-token mechanics.
- Every request does one indexed lookup, which is negligible here.
