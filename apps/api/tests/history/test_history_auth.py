"""The history routes, wired by the real app, keep ADR 0008's rules: no session, no history.
Neither check needs the database (17-history requirement 6.2)."""

import pytest
from fastapi.testclient import TestClient

from wiredex.bootstrap.app import create_app
from wiredex.bootstrap.settings import Environment, Settings

_READS = [
    ("GET", "/api/history"),
    ("GET", "/api/history?limit=10"),
    ("GET", "/api/history/part/0199aaaa-0000-7000-8000-000000000001"),
    ("GET", "/api/history/firmware/0199aaaa-0000-7000-8000-000000000002"),
]


@pytest.fixture
def client() -> TestClient:
    # https: the browser (and httpx) only send Secure cookies over TLS.
    return TestClient(
        create_app(Settings(environment=Environment.TEST)), base_url="https://testserver"
    )


@pytest.mark.parametrize(("method", "path"), _READS)
def test_history_needs_a_session(client: TestClient, method: str, path: str) -> None:
    assert client.request(method, path).status_code == 401
