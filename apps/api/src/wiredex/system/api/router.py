from fastapi import APIRouter, Response, status

from wiredex.system.api.schemas import HealthResponse, ReadinessResponse, VersionResponse
from wiredex.system.application.check_readiness import CheckReadiness
from wiredex.system.domain.build_info import BuildInfo


def create_router(build_info: BuildInfo, check_readiness: CheckReadiness) -> APIRouter:
    """Dependencies come in as arguments, so the composition root decides what runs."""
    router = APIRouter(tags=["system"])
    version = VersionResponse.from_build_info(build_info)

    @router.get("/health")
    async def health() -> HealthResponse:
        """Liveness: the process is up. Never touches the database."""
        return HealthResponse(status="ok")

    @router.get(
        "/health/ready",
        responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessResponse}},
    )
    async def ready(response: Response) -> ReadinessResponse:
        """Readiness: the API can serve real requests. 503 while the database is down."""
        readiness = await check_readiness()
        if not readiness.is_ready:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse.from_readiness(readiness)

    @router.get("/version")
    async def read_version() -> VersionResponse:
        return version

    return router
