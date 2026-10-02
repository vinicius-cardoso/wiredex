"""The history routes, wired by the real app, keep ADR 0008's rules: no session, no history; a
cookie session restores only with the CSRF header. Neither check needs the database (17-history
requirements 6.2 and 6.3)."""

import pytest
from fastapi.testclient import TestClient

from wiredex.bootstrap.app import create_app
from wiredex.bootstrap.settings import Environment, Settings
from wiredex.identity.api.cookies import CSRF_COOKIE, SESSION_COOKIE

_READS = [
    ("GET", "/api/history"),
    ("GET", "/api/history?limit=10"),
    ("GET", "/api/history/part/0199aaaa-0000-7000-8000-000000000001"),
    ("GET", "/api/history/firmware/0199aaaa-0000-7000-8000-000000000002"),
]


_WRITES = [("POST", "/api/history/changes/42/restore")]


@pytest.fixture
def client() -> TestClient:
    # https: the browser (and httpx) only send Secure cookies over TLS.
    return TestClient(
        create_app(Settings(environment=Environment.TEST)), base_url="https://testserver"
    )


@pytest.mark.parametrize(("method", "path"), [*_READS, *_WRITES])
def test_history_needs_a_session(client: TestClient, method: str, path: str) -> None:
    assert client.request(method, path).status_code == 401


@pytest.mark.parametrize(("method", "path"), _WRITES)
def test_a_cookie_restore_needs_the_csrf_header(client: TestClient, method: str, path: str) -> None:
    # Refused before any token lookup, so a made-up session cookie is enough to show it.
    client.cookies.set(SESSION_COOKIE, "some-session-token")
    client.cookies.set(CSRF_COOKIE, "the-csrf-token")
    response = client.request(method, path)
    assert response.status_code == 403
    assert response.json()["detail"] == "missing or wrong CSRF token"
