from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Match compose.yaml and .env.example, so local development needs no .env at all.
DEFAULT_DATABASE_URL = "postgresql+asyncpg://wiredex_app:wiredex_app@localhost:5442/wiredex"
DEFAULT_ADMIN_DATABASE_URL = "postgresql+asyncpg://wiredex:wiredex@localhost:5442/wiredex"

# Where the local store keeps its bytes, gitignored and mirrored on the bucket's key shape.
# apps/api/.files, found from this file rather than the working directory: `make api`, the
# debugger and Playwright all start the API inside apps/api, where a relative
# "apps/api/.files" would land in apps/api/apps/api/.files. Production uses the S3 store.
DEFAULT_FILES_DIR = str(Path(__file__).resolve().parents[3] / ".files")


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class FileStore(StrEnum):
    """Where an upload's bytes live: a local folder in development, S3 (OCI) in production."""

    LOCAL = "local"
    S3 = "s3"


class Settings(BaseSettings):
    """Runtime configuration, read from `WIREDEX_*` environment variables."""

    # env_ignore_empty: the image sets WIREDEX_BUILT_AT="" when a build has no timestamp.
    model_config = SettingsConfigDict(env_prefix="WIREDEX_", env_ignore_empty=True, frozen=True)

    environment: Environment = Environment.DEVELOPMENT
    # SecretStr keeps the passwords out of logs and reprs.
    # The API's login: wiredex_app, the restricted role that row-level security applies to.
    database_url: SecretStr = SecretStr(DEFAULT_DATABASE_URL)
    # The schema owner's login, used only by `wiredex db` commands.
    admin_database_url: SecretStr = SecretStr(DEFAULT_ADMIN_DATABASE_URL)
    # Baked into the image at build time; "unknown" when running from source.
    git_commit: str = "unknown"
    built_at: datetime | None = None

    # The file store: a local folder by default, so development needs no .env; production
    # must set `s3` and fill in the settings below, or the API refuses to start (see the
    # validator, requirement 7.1).
    file_store: FileStore = FileStore.LOCAL
    files_dir: str = DEFAULT_FILES_DIR
    # The S3-compatible endpoint (OCI Object Storage in production), region and bucket, and
    # a Customer Secret Key of a user whose only permission is that bucket (design §3).
    files_endpoint: str = ""
    files_region: str = ""
    files_bucket: str = ""
    files_access_key: str = ""
    files_secret_key: SecretStr = SecretStr("")

    @model_validator(mode="after")
    def _production_needs_the_s3_store(self) -> Settings:
        """In production the store must be `s3` and fully set, or the API refuses to start.

        A deploy with no file-store settings fails and rolls back instead of breaking uploads
        silently (requirement 7.1). Outside production the local store is fine, so nothing is
        required; that is what lets development and the tests run with no .env at all.
        """
        if self.environment is not Environment.PRODUCTION:
            return self
        if self.file_store is not FileStore.S3:
            raise ValueError("WIREDEX_FILE_STORE must be 's3' in production")
        missing = [
            name
            for name, value in {
                "WIREDEX_FILES_ENDPOINT": self.files_endpoint,
                "WIREDEX_FILES_REGION": self.files_region,
                "WIREDEX_FILES_BUCKET": self.files_bucket,
                "WIREDEX_FILES_ACCESS_KEY": self.files_access_key,
                "WIREDEX_FILES_SECRET_KEY": self.files_secret_key.get_secret_value(),
            }.items()
            if not value
        ]
        if missing:
            raise ValueError(f"missing file-store settings in production: {', '.join(missing)}")
        return self

    @property
    def docs_enabled(self) -> bool:
        return self.environment is not Environment.PRODUCTION
