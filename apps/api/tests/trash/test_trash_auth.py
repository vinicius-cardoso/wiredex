"""The trash routes, wired by the real app, keep ADR 0008's rules: no session, no trash; a cookie
session writes only with the CSRF header. Neither check needs the database
(16-soft-delete-and-trash requirements 8.3 and 8.4)."""

import pytest
from fastapi.testclient import TestClient

from wiredex.bootstrap.app import create_app
from wiredex.bootstrap.settings import Environment, Settings
from wiredex.identity.api.cookies import CSRF_COOKIE, SESSION_COOKIE

_ITEM = "/api/trash/part/0199aaaa-0000-7000-8000-000000000001"

_READS = [
    ("GET", "/api/trash"),
    ("GET", "/api/trash?limit=10"),
]

_WRITES = [
    ("POST", f"{_ITEM}/restore"),
    ("DELETE", _ITEM),
    ("DELETE", "/api/trash"),
]


@pytest.fixture
def client() -> TestClient:
    # https: the browser (and httpx) only send Secure cookies over TLS.
    return TestClient(
        create_app(Settings(environment=Environment.TEST)), base_url="https://testserver"
    )


@pytest.mark.parametrize(("method", "path"), [*_READS, *_WRITES])
def test_the_trash_needs_a_session(client: TestClient, method: str, path: str) -> None:
    assert client.request(method, path).status_code == 401


@pytest.mark.parametrize(("method", "path"), _WRITES)
def test_cookie_writes_to_the_trash_need_the_csrf_header(
    client: TestClient, method: str, path: str
) -> None:
    # Refused before any token lookup, so a made-up session cookie is enough to show it.
    client.cookies.set(SESSION_COOKIE, "some-session-token")
    client.cookies.set(CSRF_COOKIE, "the-csrf-token")
    response = client.request(method, path)
    assert response.status_code == 403
    assert response.json()["detail"] == "missing or wrong CSRF token"
