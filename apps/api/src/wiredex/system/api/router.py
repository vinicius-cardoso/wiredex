from fastapi import APIRouter

from wiredex.system.api.schemas import HealthResponse, VersionResponse
from wiredex.system.domain.build_info import BuildInfo


def create_router(build_info: BuildInfo) -> APIRouter:
    """Dependencies come in as arguments, so the composition root decides what runs."""
    router = APIRouter(tags=["system"])
    version = VersionResponse.from_build_info(build_info)

    @router.get("/health")
    async def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @router.get("/version")
    async def read_version() -> VersionResponse:
        return version

    return router
