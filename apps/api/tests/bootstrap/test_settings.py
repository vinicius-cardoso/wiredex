import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from wiredex.bootstrap.app import create_app
from wiredex.bootstrap.settings import Environment, FileStore, Settings


def _production_settings(**overrides: object) -> Settings:
    """Production settings that pass validation: the file store must be `s3` and set (7.1)."""
    return Settings(
        environment=Environment.PRODUCTION,
        file_store=FileStore.S3,
        files_endpoint="https://example.compat.objectstorage.oraclecloud.com",
        files_region="us-ashburn-1",
        files_bucket="wiredex-files",
        files_access_key="access",
        files_secret_key=SecretStr("secret-key"),
        **overrides,  # type: ignore[arg-type]
    )


def test_settings_read_prefixed_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WIREDEX_ENVIRONMENT", "production")
    monkeypatch.setenv("WIREDEX_GIT_COMMIT", "deadbeef")
    # Production refuses to start without an S3 store (requirement 7.1), so set one.
    monkeypatch.setenv("WIREDEX_FILE_STORE", "s3")
    monkeypatch.setenv("WIREDEX_FILES_ENDPOINT", "https://example.oraclecloud.com")
    monkeypatch.setenv("WIREDEX_FILES_REGION", "us-ashburn-1")
    monkeypatch.setenv("WIREDEX_FILES_BUCKET", "wiredex-files")
    monkeypatch.setenv("WIREDEX_FILES_ACCESS_KEY", "access")
    monkeypatch.setenv("WIREDEX_FILES_SECRET_KEY", "secret-key")

    settings = Settings()

    assert settings.environment is Environment.PRODUCTION
    assert settings.git_commit == "deadbeef"


@pytest.mark.parametrize("path", ["/api/docs", "/api/openapi.json"])
def test_docs_are_hidden_in_production(path: str) -> None:
    client = TestClient(create_app(_production_settings()))

    assert client.get(path).status_code == 404


@pytest.mark.parametrize("path", ["/api/docs", "/api/openapi.json"])
def test_docs_are_served_outside_production(path: str) -> None:
    client = TestClient(create_app(Settings(environment=Environment.DEVELOPMENT)))

    assert client.get(path).status_code == 200


def test_empty_variables_count_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WIREDEX_BUILT_AT", "")

    assert Settings().built_at is None
