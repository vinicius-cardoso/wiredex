from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel

from wiredex.system.domain.build_info import BuildInfo
from wiredex.system.domain.readiness import Readiness


class HealthResponse(BaseModel):
    status: Literal["ok"]


class VersionResponse(BaseModel):
    version: str
    commit: str
    built_at: datetime | None

    @classmethod
    def from_build_info(cls, build_info: BuildInfo) -> Self:
        return cls(
            version=build_info.version,
            commit=build_info.commit,
            built_at=build_info.built_at,
        )


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    database: Literal["up", "down"]

    @classmethod
    def from_readiness(cls, readiness: Readiness) -> Self:
        return cls(
            status="ready" if readiness.is_ready else "not_ready",
            database="up" if readiness.database_reachable else "down",
        )
