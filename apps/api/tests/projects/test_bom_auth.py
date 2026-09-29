"""The BOM routes, wired by the real app, keep ADR 0008's rules: no session, no BOM; a cookie
session writes a line only with the CSRF header. Neither check needs the database
(requirements 9.5 and 9.6)."""

import pytest
from fastapi.testclient import TestClient

from wiredex.bootstrap.app import create_app
from wiredex.bootstrap.settings import Environment, Settings
from wiredex.identity.api.cookies import CSRF_COOKIE, SESSION_COOKIE

_BOM = "/api/projects/revisions/0199aaaa-0000-7000-8000-000000000002/bom"
_LINE = f"{_BOM}/lines/0199aaaa-0000-7000-8000-000000000003"
_BODY = {"part_id": "0199aaaa-0000-7000-8000-000000000004", "designators": "R1"}


@pytest.fixture
def client() -> TestClient:
    # https: the browser (and httpx) only send Secure cookies over TLS.
    return TestClient(
        create_app(Settings(environment=Environment.TEST)), base_url="https://testserver"
    )


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", _BOM),
        ("POST", f"{_BOM}/lines"),
        ("PATCH", _LINE),
        ("DELETE", _LINE),
    ],
)
def test_boms_need_a_session(client: TestClient, method: str, path: str) -> None:
    assert client.request(method, path, json=_BODY).status_code == 401


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", f"{_BOM}/lines"),
        ("PATCH", _LINE),
        ("DELETE", _LINE),
    ],
)
def test_cookie_writes_to_a_bom_need_the_csrf_header(
    client: TestClient, method: str, path: str
) -> None:
    # Refused before any token lookup, so a made-up session cookie is enough to show it.
    client.cookies.set(SESSION_COOKIE, "some-session-token")
    client.cookies.set(CSRF_COOKIE, "the-csrf-token")

    response = client.request(method, path, json=_BODY)

    assert response.status_code == 403
    assert response.json()["detail"] == "missing or wrong CSRF token"
