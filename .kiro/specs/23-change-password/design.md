# Design Document: change password

## Overview

One use case, `ChangePassword`, one route, `POST /api/auth/password`, and one form on the
devices page. Answers [requirements.md](requirements.md). No migration: the hash column is
the one a login reads.

## Architecture

All inside `identity`. The use case takes the ports a login takes: the unit of work, the
clock, the hasher and the throttle, the same throttle instance, so the limits live in one
place.

## Components and Interfaces

### Domain

- `User.change_password(hash)` and `User.ensure_unlike_account(password)`.
- `WrongPasswordError`, `SamePasswordError`, `PasswordLikeAccountError`; `WeakPasswordError`
  is the one `Password` already raises.

### Application

`ChangePassword(current: CurrentUser, current_password: str, new_password: str)`, in this
order:

1. Blocked? `TooManyAttemptsError`, before any hashing, so a locked change costs nothing.
2. Read the user again in this unit of work and verify the current password. A string that
   can't be a `Password` still runs one verification against no hash, the hasher's decoy, so
   the answer takes as long. Wrong: count the failure, `WrongPasswordError`.
3. Build the new `Password`, compare it with the current one, check it against the account.
4. Hash, set, remove every other session, commit, clear the failures.

The passwords arrive as `str` so step 2 can answer "wrong" for a malformed current one instead
of a validation error that would tell a guesser about the length rule.

### Throttle

`InMemoryLoginThrottle` gains a third prefix, `password`, limit 5, keyed by user id. It is in
memory, as the login's is (ADR 0009): a restart resets it, which only ever helps the owner.

### API

`POST /api/auth/password` with `{current_password, new_password}` answers
`{revoked_sessions}`. Refusals are 422 with `{code, field, message}`, or 429. Never 401: the
web reads a 401 as "logged out" and would send the owner to the login page mid-change.

### Web

`ChangePasswordForm` on `SessionsPage`, where the result shows: the list of devices shrinks to
this one. The form is uncontrolled: the three values are read from `FormData` on submit and
the form is reset on success, so nothing is kept in React state. The menu item becomes
"Devices and password".

## What this doesn't do

- The session that made the change keeps its token. Rotating it would close the case of a
  thief who already holds that very session, but they could also just keep using it before
  the change; logging a device out is what the devices list is for.
- No email is sent, since Wiredex sends none. The devices list is where a change shows.
- Nothing is written to the application log about the change: there is no audit log for
  accounts yet, and a line with half the story is worse than none.

## Testing

Use-case tests for every rule and the order they answer in; API tests for the statuses, the
CSRF header and the bodies; an integration test that the stored value is an Argon2id hash and
the other sessions are gone; Vitest for the form; and a journey on a guest account made for
the run, so the shared e2e account keeps its password.
