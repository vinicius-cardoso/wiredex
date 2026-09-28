"""The inventory routes, wired by the real app, keep ADR 0008's rules: no session, no data;
a cookie session writes only with the CSRF header. Neither check needs the database."""

import pytest
from fastapi.testclient import TestClient

from wiredex.bootstrap.app import create_app
from wiredex.bootstrap.settings import Environment, Settings
from wiredex.identity.api.cookies import CSRF_COOKIE, SESSION_COOKIE

_LOCATION = "/api/inventory/locations/0199aaaa-0000-7000-8000-000000000001"
_PART = "0199aaaa-0000-7000-8000-000000000001"
_UNIT = "/api/inventory/units/0199aaaa-0000-7000-8000-000000000002"


@pytest.fixture
def client() -> TestClient:
    # https: the browser (and httpx) only send Secure cookies over TLS.
    return TestClient(
        create_app(Settings(environment=Environment.TEST)), base_url="https://testserver"
    )


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/inventory/locations"),
        ("POST", "/api/inventory/locations"),
        ("PATCH", _LOCATION),
        ("DELETE", _LOCATION),
        ("POST", "/api/inventory/receive"),
        ("POST", "/api/inventory/adjust"),
        ("POST", "/api/inventory/move"),
        ("GET", f"/api/inventory/parts/stock?part_id={_PART}"),
        ("GET", f"/api/inventory/parts/{_PART}/stock"),
        # Units: the receive, the reads and search, one unit, and its five actions.
        ("POST", "/api/inventory/units"),
        ("GET", "/api/inventory/units?search=wx-u"),
        ("GET", f"/api/inventory/parts/{_PART}/units"),
        ("GET", _UNIT),
        ("PATCH", _UNIT),
        ("POST", f"{_UNIT}/move"),
        ("POST", f"{_UNIT}/retire"),
        ("POST", f"{_UNIT}/unretire"),
        ("DELETE", _UNIT),
        # Intake: quick-add, a sheet's preview and import, and the template download.
        ("POST", "/api/inventory/quick-add"),
        ("POST", "/api/inventory/imports/preview"),
        ("POST", "/api/inventory/imports"),
        ("GET", "/api/inventory/imports/template"),
    ],
)
def test_inventory_needs_a_session(client: TestClient, method: str, path: str) -> None:
    assert client.request(method, path, json={"name": "Lab"}).status_code == 401


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/inventory/locations"),
        ("PATCH", _LOCATION),
        ("DELETE", _LOCATION),
        # The three movements are POSTs, so the cookie session has to carry the CSRF header
        # (ADR 0008): the check is on the method, not on what it does.
        ("POST", "/api/inventory/receive"),
        ("POST", "/api/inventory/adjust"),
        ("POST", "/api/inventory/move"),
        # Every unit write is a POST/PATCH/DELETE, so each carries the CSRF header too.
        ("POST", "/api/inventory/units"),
        ("PATCH", _UNIT),
        ("POST", f"{_UNIT}/move"),
        ("POST", f"{_UNIT}/retire"),
        ("POST", f"{_UNIT}/unretire"),
        ("DELETE", _UNIT),
        # Intake's three POSTs, the preview too: it writes nothing, but it is a POST, and the
        # check is on the method (requirement 10.4).
        ("POST", "/api/inventory/quick-add"),
        ("POST", "/api/inventory/imports/preview"),
        ("POST", "/api/inventory/imports"),
    ],
)
def test_cookie_writes_to_inventory_need_the_csrf_header(
    client: TestClient, method: str, path: str
) -> None:
    # Refused before any token lookup, so a made-up session cookie is enough to show it.
    client.cookies.set(SESSION_COOKIE, "some-session-token")
    client.cookies.set(CSRF_COOKIE, "the-csrf-token")

    response = client.request(method, path, json={"name": "Lab"})

    assert response.status_code == 403
    assert response.json()["detail"] == "missing or wrong CSRF token"
