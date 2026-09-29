"""The netlist routes, wired by the real app, keep ADR 0008's rules: no session, no netlist; a
cookie session writes a net only with the CSRF header. Neither check needs the database
(11-netlist-editor requirements 8.5 and 8.6)."""

import pytest
from fastapi.testclient import TestClient

from wiredex.bootstrap.app import create_app
from wiredex.bootstrap.settings import Environment, Settings
from wiredex.identity.api.cookies import CSRF_COOKIE, SESSION_COOKIE

_NETLIST = "/api/projects/revisions/0199aaaa-0000-7000-8000-000000000002/netlist"
_NET = f"{_NETLIST}/nets/0199aaaa-0000-7000-8000-000000000003"
_BODY = {"name": "SDA", "pins": "U1.25"}


@pytest.fixture
def client() -> TestClient:
    return TestClient(
        create_app(Settings(environment=Environment.TEST)), base_url="https://testserver"
    )


@pytest.mark.parametrize(
    ("method", "path"),
    [("GET", _NETLIST), ("POST", f"{_NETLIST}/nets"), ("PATCH", _NET), ("DELETE", _NET)],
)
def test_netlists_need_a_session(client: TestClient, method: str, path: str) -> None:
    assert client.request(method, path, json=_BODY).status_code == 401


@pytest.mark.parametrize(
    ("method", "path"), [("POST", f"{_NETLIST}/nets"), ("PATCH", _NET), ("DELETE", _NET)]
)
def test_cookie_writes_to_a_netlist_need_the_csrf_header(
    client: TestClient, method: str, path: str
) -> None:
    client.cookies.set(SESSION_COOKIE, "some-session-token")
    client.cookies.set(CSRF_COOKIE, "the-csrf-token")

    response = client.request(method, path, json=_BODY)

    assert response.status_code == 403
    assert response.json()["detail"] == "missing or wrong CSRF token"
