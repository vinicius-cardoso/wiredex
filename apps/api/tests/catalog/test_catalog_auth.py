"""The catalog routes, wired by the real app, keep ADR 0008's rules: no session, no data;
a cookie session writes only with the CSRF header. Neither check needs the database."""

import pytest
from fastapi.testclient import TestClient

from wiredex.bootstrap.app import create_app
from wiredex.bootstrap.settings import Environment, Settings
from wiredex.identity.api.cookies import CSRF_COOKIE, SESSION_COOKIE


@pytest.fixture
def client() -> TestClient:
    # https: the browser (and httpx) only send Secure cookies over TLS.
    return TestClient(
        create_app(Settings(environment=Environment.TEST)), base_url="https://testserver"
    )


_ATTACHMENT = "/api/files/attachments/0199aaaa-0000-7000-8000-000000000001"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/catalog/categories"),
        ("GET", "/api/catalog/parts"),
        ("POST", "/api/catalog/categories"),
        ("DELETE", "/api/catalog/parts/0199aaaa-0000-7000-8000-000000000001"),
        ("GET", "/api/catalog/parts/0199aaaa-0000-7000-8000-000000000001/pinout"),
        ("PUT", "/api/catalog/parts/0199aaaa-0000-7000-8000-000000000001/pinout"),
        # Files ride the same session dependency (design §3), so they answer the same way.
        ("GET", "/api/files/attachments"),
        ("POST", "/api/files/attachments"),
        ("PATCH", _ATTACHMENT),
        ("DELETE", _ATTACHMENT),
        ("GET", f"{_ATTACHMENT}/content"),
    ],
)
def test_the_catalog_needs_a_session(client: TestClient, method: str, path: str) -> None:
    assert client.request(method, path, json={"name": "Passives"}).status_code == 401


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/catalog/categories"),
        ("PATCH", "/api/catalog/parts/0199aaaa-0000-7000-8000-000000000001"),
        ("DELETE", "/api/catalog/categories/0199aaaa-0000-7000-8000-000000000001"),
        ("PUT", "/api/catalog/parts/0199aaaa-0000-7000-8000-000000000001/pinout"),
        # The files writes: upload, change and remove all need the CSRF header (ADR 0008).
        ("POST", "/api/files/attachments"),
        ("PATCH", _ATTACHMENT),
        ("DELETE", _ATTACHMENT),
    ],
)
def test_cookie_writes_to_the_catalog_need_the_csrf_header(
    client: TestClient, method: str, path: str
) -> None:
    # Refused before any token lookup, so a made-up session cookie is enough to show it.
    client.cookies.set(SESSION_COOKIE, "some-session-token")
    client.cookies.set(CSRF_COOKIE, "the-csrf-token")

    response = client.request(method, path, json={"name": "Passives"})

    assert response.status_code == 403
    assert response.json()["detail"] == "missing or wrong CSRF token"
