"""The search route, wired by the real app, keeps ADR 0008's rule: no session, no search. It needs
no database (19-command-palette, requirement 2.3)."""

import pytest
from fastapi.testclient import TestClient

from wiredex.bootstrap.app import create_app
from wiredex.bootstrap.settings import Environment, Settings


@pytest.fixture
def client() -> TestClient:
    # https: the browser (and httpx) only send Secure cookies over TLS.
    return TestClient(
        create_app(Settings(environment=Environment.TEST)), base_url="https://testserver"
    )


@pytest.mark.parametrize("path", ["/api/search?q=sensor", "/api/search?q=sensor&limit=20"])
def test_the_search_needs_a_session(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 401
