"""The browser side of ADR 0008: a session cookie plus a double-submit CSRF cookie."""

import secrets

from fastapi import Response

from wiredex.identity.domain.session import SLIDING_LIFETIME
from wiredex.identity.domain.values import SessionToken

# __Host- makes the browser insist on Secure, Path=/ and no Domain: the cookie can't be
# set or read by any other subdomain of vinilabs.cc.
SESSION_COOKIE = "__Host-wiredex_session"
# Readable by the page's own JavaScript, which echoes it in CSRF_HEADER on writes.
# Another site can make the browser send cookies, but can't read this one.
CSRF_COOKIE = "__Host-wiredex_csrf"
CSRF_HEADER = "X-CSRF-Token"


def set_session_cookies(response: Response, token: SessionToken) -> None:
    max_age = int(SLIDING_LIFETIME.total_seconds())
    response.set_cookie(
        SESSION_COOKIE, token.value, max_age=max_age, secure=True, httponly=True, samesite="lax"
    )
    response.set_cookie(
        CSRF_COOKIE,
        secrets.token_urlsafe(32),
        max_age=max_age,
        secure=True,
        httponly=False,
        samesite="lax",
    )


def clear_session_cookies(response: Response) -> None:
    for name in (SESSION_COOKIE, CSRF_COOKIE):
        response.delete_cookie(name, secure=True, httponly=name == SESSION_COOKIE, samesite="lax")
