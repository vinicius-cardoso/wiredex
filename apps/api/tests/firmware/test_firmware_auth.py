"""The firmware routes, wired by the real app, keep ADR 0008's rules: no session, no firmware; a
cookie session writes only with the CSRF header. Neither check needs the database
(13-firmware-versions requirements 9.5 and 9.6; the flash log's, 15-flash-log 6.4 and 6.5)."""

import pytest
from fastapi.testclient import TestClient

from wiredex.bootstrap.app import create_app
from wiredex.bootstrap.settings import Environment, Settings
from wiredex.identity.api.cookies import CSRF_COOKIE, SESSION_COOKIE

_FIRMWARE = "/api/firmware/0199aaaa-0000-7000-8000-000000000001"
_REVISION = "0199aaaa-0000-7000-8000-000000000002"
_VERSION = "/api/firmware/versions/0199aaaa-0000-7000-8000-000000000003"
_FILE = f"{_VERSION}/files/0199aaaa-0000-7000-8000-000000000004"
_UNIT = "/api/firmware/units/0199aaaa-0000-7000-8000-000000000005"
_FLASH = "/api/firmware/flashes/0199aaaa-0000-7000-8000-000000000006"
_BODY = {"name": "Weather station", "target": "esp32:esp32:esp32", "framework": "arduino"}

_READS = [
    ("GET", "/api/firmware"),
    ("GET", "/api/firmware?search=esp32"),
    ("GET", f"/api/firmware/revisions/{_REVISION}"),
    ("GET", _FIRMWARE),
    ("GET", _VERSION),
    # 15-flash-log requirement 6.4: a board's log and a firmware's boards.
    ("GET", _UNIT),
    ("GET", f"{_FIRMWARE}/boards"),
]
# Every write, the link's PUT among them: a cookie session sends each with the CSRF header.
_WRITES = [
    ("POST", "/api/firmware"),
    ("PATCH", _FIRMWARE),
    ("DELETE", _FIRMWARE),
    ("PUT", f"{_FIRMWARE}/revisions/{_REVISION}"),
    ("DELETE", f"{_FIRMWARE}/revisions/{_REVISION}"),
    ("POST", f"{_FIRMWARE}/versions"),
    ("PATCH", _VERSION),
    ("POST", f"{_VERSION}/release"),
    ("DELETE", _VERSION),
    ("POST", f"{_VERSION}/files"),
    ("PATCH", _FILE),
    ("DELETE", _FILE),
    # 15-flash-log requirement 6.5: a flash logged and one removed.
    ("POST", f"{_UNIT}/flashes"),
    ("DELETE", _FLASH),
]


@pytest.fixture
def client() -> TestClient:
    # https: the browser (and httpx) only send Secure cookies over TLS.
    return TestClient(
        create_app(Settings(environment=Environment.TEST)), base_url="https://testserver"
    )


@pytest.mark.parametrize(("method", "path"), [*_READS, *_WRITES])
def test_firmware_needs_a_session(client: TestClient, method: str, path: str) -> None:
    assert client.request(method, path, json=_BODY).status_code == 401


@pytest.mark.parametrize(("method", "path"), _WRITES)
def test_cookie_writes_to_firmware_need_the_csrf_header(
    client: TestClient, method: str, path: str
) -> None:
    # Refused before any token lookup, so a made-up session cookie is enough to show it.
    client.cookies.set(SESSION_COOKIE, "some-session-token")
    client.cookies.set(CSRF_COOKIE, "the-csrf-token")

    response = client.request(method, path, json=_BODY)

    assert response.status_code == 403
    assert response.json()["detail"] == "missing or wrong CSRF token"
