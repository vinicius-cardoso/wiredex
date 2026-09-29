"""The lifecycle routes, wired by the real app, keep ADR 0008's rules: no session, no
lifecycle; a cookie session runs a transition only with the CSRF header. Neither check needs
the database (requirements 11.4, 11.5), and a revision of another workspace is 404, not 403,
which the use-case and API tests cover once past these gates."""

import pytest
from fastapi.testclient import TestClient

from wiredex.bootstrap.app import create_app
from wiredex.bootstrap.settings import Environment, Settings
from wiredex.identity.api.cookies import CSRF_COOKIE, SESSION_COOKIE

_REVISION = "/api/projects/revisions/0199aaaa-0000-7000-8000-000000000002"
_PART = "/api/projects/parts/0199aaaa-0000-7000-8000-000000000005/holdings"


@pytest.fixture
def client() -> TestClient:
    # https: the browser (and httpx) only send Secure cookies over TLS.
    return TestClient(
        create_app(Settings(environment=Environment.TEST)), base_url="https://testserver"
    )


def _body(path: str) -> dict[str, object]:
    if path.endswith("/reserve"):
        return {"units": []}
    if path.endswith("/dismantle"):
        return {"location_id": "0199aaaa-0000-7000-8000-000000000006"}
    return {}


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", f"{_REVISION}/reserve"),
        ("POST", f"{_REVISION}/cancel"),
        ("POST", f"{_REVISION}/build"),
        ("POST", f"{_REVISION}/dismantle"),
        ("GET", f"{_REVISION}/lifecycle"),
        ("GET", _REVISION),
        ("GET", _PART),
    ],
)
def test_lifecycle_routes_need_a_session(client: TestClient, method: str, path: str) -> None:
    assert client.request(method, path, json=_body(path)).status_code == 401


@pytest.mark.parametrize(
    "path",
    [
        f"{_REVISION}/reserve",
        f"{_REVISION}/cancel",
        f"{_REVISION}/build",
        f"{_REVISION}/dismantle",
    ],
)
def test_a_cookie_transition_needs_the_csrf_header(client: TestClient, path: str) -> None:
    # Refused before any token lookup, so a made-up session cookie is enough to show it.
    client.cookies.set(SESSION_COOKIE, "some-session-token")
    client.cookies.set(CSRF_COOKIE, "the-csrf-token")

    response = client.post(path, json=_body(path))

    assert response.status_code == 403
    assert response.json()["detail"] == "missing or wrong CSRF token"
