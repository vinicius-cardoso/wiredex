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

## Changing a password (23-change-password)

A logged-in user changes their own password on the devices page.

- **The current password is asked again.** A session is enough to use the app, not to take
  the account: a stolen cookie or an unlocked laptop can't change the password.
- **Wrong tries are limited**, five in fifteen minutes per user, counted apart from failed
  logins so the form can't be used to lock the login.
- **Every other session ends** when the password changes; the one that made the change
  stays. The token of that session is not rotated.
- **The new password** is 12 to 1,024 characters, differs from the current one, and isn't the
  email or the name. No composition rules and no breached-password lookup, which would send
  something derived from the password to a third party.
- A refusal is a 422 with a code, never a 401: the session is fine, and the web reads a 401
  as logged out.
- There is still no reset by email. A locked-out owner uses the CLI on the host.

## Consequences

- Revocation is a row delete. There are no refresh-token mechanics.
- Every request does one indexed lookup, which is negligible here.
