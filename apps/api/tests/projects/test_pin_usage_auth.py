"""The pin usage route, wired by the real app, keeps ADR 0008's rule: no session, no pin usage.
It is a read, so no CSRF (12-wiring-validation requirement 8.3)."""

from fastapi.testclient import TestClient

from wiredex.bootstrap.app import create_app
from wiredex.bootstrap.settings import Environment, Settings

_PIN_USAGE = "/api/projects/parts/0199aaaa-0000-7000-8000-000000000002/pin-usage"


def test_pin_usage_needs_a_session() -> None:
    client = TestClient(
        create_app(Settings(environment=Environment.TEST)), base_url="https://testserver"
    )

    assert client.get(_PIN_USAGE).status_code == 401
