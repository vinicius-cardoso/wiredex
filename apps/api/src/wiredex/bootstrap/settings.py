from datetime import datetime
from enum import StrEnum

from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """Runtime configuration, read from `WIREDEX_*` environment variables."""

    model_config = SettingsConfigDict(env_prefix="WIREDEX_", frozen=True)

    environment: Environment = Environment.DEVELOPMENT
    # Baked into the image at build time; "unknown" when running from source.
    git_commit: str = "unknown"
    built_at: datetime | None = None

    @property
    def docs_enabled(self) -> bool:
        return self.environment is not Environment.PRODUCTION
