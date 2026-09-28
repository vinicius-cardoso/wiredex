"""The projects routes, wired by the real app, keep ADR 0008's rules: no session, no data;
a cookie session writes only with the CSRF header. Neither check needs the database
(requirements 8.5 and 8.6)."""

import pytest
from fastapi.testclient import TestClient

from wiredex.bootstrap.app import create_app
from wiredex.bootstrap.settings import Environment, Settings
from wiredex.identity.api.cookies import CSRF_COOKIE, SESSION_COOKIE

_PROJECT = "/api/projects/0199aaaa-0000-7000-8000-000000000001"
_REVISION = "/api/projects/revisions/0199aaaa-0000-7000-8000-000000000002"


@pytest.fixture
def client() -> TestClient:
    # https: the browser (and httpx) only send Secure cookies over TLS.
    return TestClient(
        create_app(Settings(environment=Environment.TEST)), base_url="https://testserver"
    )


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/projects"),
        ("GET", "/api/projects?q=weather&tag=esp32"),
        ("POST", "/api/projects"),
        ("GET", "/api/projects/tags"),
        ("GET", _PROJECT),
        ("PATCH", _PROJECT),
        ("DELETE", _PROJECT),
        ("POST", f"{_PROJECT}/revisions"),
        ("PATCH", _REVISION),
        ("DELETE", _REVISION),
        ("POST", f"{_REVISION}/fork"),
    ],
)
def test_projects_need_a_session(client: TestClient, method: str, path: str) -> None:
    assert client.request(method, path, json={"name": "Weather station"}).status_code == 401


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/projects"),
        ("PATCH", _PROJECT),
        ("DELETE", _PROJECT),
        ("POST", f"{_PROJECT}/revisions"),
        ("PATCH", _REVISION),
        ("DELETE", _REVISION),
        # A fork is a POST, so the cookie session has to carry the CSRF header (ADR 0008).
        ("POST", f"{_REVISION}/fork"),
    ],
)
def test_cookie_writes_to_projects_need_the_csrf_header(
    client: TestClient, method: str, path: str
) -> None:
    # Refused before any token lookup, so a made-up session cookie is enough to show it.
    client.cookies.set(SESSION_COOKIE, "some-session-token")
    client.cookies.set(CSRF_COOKIE, "the-csrf-token")

    response = client.request(method, path, json={"name": "Weather station", "label": "B"})

    assert response.status_code == 403
    assert response.json()["detail"] == "missing or wrong CSRF token"
