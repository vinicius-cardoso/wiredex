# Requirements Document

## Introduction

Change password: a person changes their own password from the app. Until now a password
could only be set when the account was created, from the CLI, so a password that had leaked
could not be replaced without the host.

It builds on ADR 0008 (sessions) and the devices page. [design.md](design.md) answers these.

Acceptance criteria use EARS: `WHEN <condition> THE SYSTEM SHALL <behaviour>`.

Owner decision (2026-10-11): **a user can change their own password, with security
awareness.**

Decisions taken without the owner, for the owner to review:

1. **The current password is asked again.** A session alone can't change the password, so a
   stolen cookie or an unlocked laptop can't take the account over or lock its owner out.
2. **Wrong current passwords are limited**, five in fifteen minutes per user, as failed logins
   are. The count is separate from the login's, so a prankster at the form can't lock the
   login.
3. **Changing the password logs every other device out** and keeps the one that made the
   change. That is the point of changing a leaked password.
4. **The new password has to differ from the current one and can't be or contain the email or
   the name.** No composition rules (a digit, a symbol): length does the work, as NIST SP
   800-63B advises, and the floor stays at 12 characters.
5. **No breached-password lookup.** It would send (part of a hash of) the password to a third
   party; Wiredex contacts nothing outside itself.
6. **Guests can change theirs too.** The owner saw a guest's first password when inviting
   them, so a guest has more reason to change it than anyone.
7. **No "forgot my password".** Wiredex sends no email; an owner who is locked out uses the
   CLI on the host.

## Requirements

### Requirement 1: changing the password

1. WHEN a logged-in user sends their current password and a new one THE SYSTEM SHALL store the
   new one hashed with Argon2id and answer how many other sessions it ended.
2. WHEN the password changes THE SYSTEM SHALL end every session of that user except the one
   that made the request.
3. WHEN the password changes THE SYSTEM SHALL accept only the new password at the next login.
4. THE request SHALL need a session, and the CSRF header when the session is a cookie.

### Requirement 2: refusals

1. WHEN the current password is wrong THE SYSTEM SHALL refuse with 422 `wrong_password` on
   `current_password`, change nothing and end no session.
2. WHEN the current password is one no password could be (empty, shorter than 12, longer than
   1,024) THE SYSTEM SHALL answer exactly as for a wrong one, and take as long.
3. WHEN five wrong current passwords were given for a user inside fifteen minutes THE SYSTEM
   SHALL refuse every further change for that user with 429 until the window passes, the right
   password included.
4. WHEN a change succeeds THE SYSTEM SHALL forget the wrong tries before it.
5. WHEN the new password is shorter than 12 or longer than 1,024 characters THE SYSTEM SHALL
   refuse with 422 `weak_password` on `new_password`.
6. WHEN the new password is the current one THE SYSTEM SHALL refuse with 422 `same_password`.
7. WHEN the new password, ignoring case, holds the email, its part before the `@` or the name
   (each when it has four characters or more) THE SYSTEM SHALL refuse with 422
   `password_like_account`.
8. THE SYSTEM SHALL say what is wrong with the new password only once the current one is right.
9. A refusal SHALL never be a 401 or a 403, and SHALL never repeat either password.

### Requirement 3: the page

1. THE devices page SHALL hold a form with the current password, the new one and the new one
   again, each hidden as typed, with a control to show them.
2. THE fields SHALL tell a password manager what they are (`current-password`,
   `new-password`, and the account's email as `username`).
3. THE form SHALL say, before anything is typed, how long a password must be and what makes a
   good one, and that the other devices will be logged out.
4. WHEN the form can tell the request would be refused (no current password, a new one too
   short, the same as the current one, or the two new ones different) THE SYSTEM SHALL say so
   and send nothing.
5. WHEN the change succeeds THE SYSTEM SHALL clear the three fields, say the password changed
   and how many other devices were logged out, and show the devices list again.
6. WHEN the change is refused THE SYSTEM SHALL say why and that nothing changed, mark the field
   it is about, and for a wrong current password clear that field and keep the new one.
7. THE form SHALL NOT keep a password in the page's state.
8. Every string SHALL exist in English and Brazilian Portuguese.
