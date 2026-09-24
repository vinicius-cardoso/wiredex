"""Finds the token a request presents, and enforces CSRF when it came from a cookie."""

import secrets
from dataclasses import dataclass

from fastapi import HTTPException, Request, status

from wiredex.identity.api.cookies import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE
from wiredex.identity.domain.values import SessionToken

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


@dataclass(frozen=True, slots=True)
class PresentedToken:
    token: SessionToken
    from_cookie: bool


def presented_token(request: Request) -> PresentedToken | None:
    """A Bearer header (mobile) wins over the session cookie (web)."""
    scheme, _, value = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() == "bearer" and value:
        return PresentedToken(SessionToken(value.strip()), from_cookie=False)
    cookie = request.cookies.get(SESSION_COOKIE)
    return None if not cookie else PresentedToken(SessionToken(cookie), from_cookie=True)


def require_csrf(request: Request, presented: PresentedToken) -> None:
    """Cookie-authenticated writes must echo the CSRF cookie in a header."""
    if not presented.from_cookie or request.method in SAFE_METHODS:
        return
    expected = request.cookies.get(CSRF_COOKIE, "")
    sent = request.headers.get(CSRF_HEADER, "")
    if not expected or not secrets.compare_digest(expected, sent):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "missing or wrong CSRF token")
