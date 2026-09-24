from datetime import datetime
from enum import StrEnum

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Match compose.yaml and .env.example, so local development needs no .env at all.
DEFAULT_DATABASE_URL = "postgresql+asyncpg://wiredex_app:wiredex_app@localhost:5442/wiredex"
DEFAULT_ADMIN_DATABASE_URL = "postgresql+asyncpg://wiredex:wiredex@localhost:5442/wiredex"


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


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

    @property
    def docs_enabled(self) -> bool:
        return self.environment is not Environment.PRODUCTION
