import pytest
from pydantic import SecretStr, ValidationError

from wiredex.bootstrap.settings import DEFAULT_FILES_DIR, Environment, FileStore, Settings


def _production_s3_settings() -> Settings:
    return Settings(
        environment=Environment.PRODUCTION,
        file_store=FileStore.S3,
        files_endpoint="https://example.compat.objectstorage.oraclecloud.com",
        files_region="us-ashburn-1",
        files_bucket="wiredex-files",
        files_access_key="access",
        files_secret_key=SecretStr("s3cr3t-customer-key"),
    )


def test_the_store_is_local_by_default() -> None:
    settings = Settings()

    assert settings.file_store is FileStore.LOCAL
    assert settings.files_dir == DEFAULT_FILES_DIR


def test_development_needs_no_file_store_settings() -> None:
    settings = Settings(environment=Environment.DEVELOPMENT)

    assert settings.file_store is FileStore.LOCAL


def test_production_refuses_to_start_without_the_s3_store() -> None:
    with pytest.raises(ValidationError, match="must be 's3' in production"):
        Settings(environment=Environment.PRODUCTION)


def test_production_refuses_to_start_with_missing_s3_settings() -> None:
    with pytest.raises(ValidationError, match="missing file-store settings"):
        Settings(environment=Environment.PRODUCTION, file_store=FileStore.S3)


def test_production_lists_every_missing_s3_setting() -> None:
    with pytest.raises(ValidationError) as raised:
        Settings(environment=Environment.PRODUCTION, file_store=FileStore.S3)

    message = str(raised.value)
    for name in (
        "WIREDEX_FILES_ENDPOINT",
        "WIREDEX_FILES_REGION",
        "WIREDEX_FILES_BUCKET",
        "WIREDEX_FILES_ACCESS_KEY",
        "WIREDEX_FILES_SECRET_KEY",
    ):
        assert name in message


def test_production_starts_with_the_s3_store_fully_set() -> None:
    settings = _production_s3_settings()

    assert settings.file_store is FileStore.S3
    assert settings.files_bucket == "wiredex-files"


def test_the_secret_key_never_shows_in_repr() -> None:
    settings = _production_s3_settings()

    assert "s3cr3t-customer-key" not in repr(settings)
