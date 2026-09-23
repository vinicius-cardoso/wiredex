import pytest
from fastapi.testclient import TestClient

from wiredex.bootstrap.app import create_app
from wiredex.bootstrap.settings import Environment, Settings


def test_settings_read_prefixed_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WIREDEX_ENVIRONMENT", "production")
    monkeypatch.setenv("WIREDEX_GIT_COMMIT", "deadbeef")

    settings = Settings()

    assert settings.environment is Environment.PRODUCTION
    assert settings.git_commit == "deadbeef"


@pytest.mark.parametrize("path", ["/api/docs", "/api/openapi.json"])
def test_docs_are_hidden_in_production(path: str) -> None:
    client = TestClient(create_app(Settings(environment=Environment.PRODUCTION)))

    assert client.get(path).status_code == 404


@pytest.mark.parametrize("path", ["/api/docs", "/api/openapi.json"])
def test_docs_are_served_outside_production(path: str) -> None:
    client = TestClient(create_app(Settings(environment=Environment.DEVELOPMENT)))

    assert client.get(path).status_code == 200


def test_empty_variables_count_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WIREDEX_BUILT_AT", "")

    assert Settings().built_at is None
