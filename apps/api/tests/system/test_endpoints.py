from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

import wiredex
from wiredex.bootstrap.app import create_app
from wiredex.bootstrap.settings import Environment, Settings

BUILT_AT = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)


@pytest.fixture
def client() -> TestClient:
    settings = Settings(environment=Environment.TEST, git_commit="a1b2c3d4e5f6", built_at=BUILT_AT)
    return TestClient(create_app(settings))


def test_health_reports_ok(client: TestClient) -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_version_reports_release_and_build(client: TestClient) -> None:
    response = client.get("/api/version")

    assert response.json() == {
        "version": wiredex.__version__,
        "commit": "a1b2c3d4e5f6",
        "built_at": "2026-09-23T12:00:00Z",
    }


def test_version_from_source_has_unknown_build() -> None:
    client = TestClient(create_app(Settings(environment=Environment.TEST)))

    assert client.get("/api/version").json()["commit"] == "unknown"
