from fastapi import FastAPI

import wiredex
from wiredex.bootstrap.settings import Settings
from wiredex.system.api.router import create_router as create_system_router
from wiredex.system.domain.build_info import BuildInfo

API_PREFIX = "/api"


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application. Uvicorn calls this with `--factory`."""
    settings = settings or Settings()
    app = FastAPI(
        title="Wiredex API",
        version=wiredex.__version__,
        openapi_url=_docs_path(settings, "/openapi.json"),
        docs_url=_docs_path(settings, "/docs"),
        redoc_url=None,
    )
    app.include_router(create_system_router(_build_info(settings)), prefix=API_PREFIX)
    return app


def _docs_path(settings: Settings, path: str) -> str | None:
    if not settings.docs_enabled:
        return None
    return f"{API_PREFIX}{path}"


def _build_info(settings: Settings) -> BuildInfo:
    return BuildInfo(
        version=wiredex.__version__,
        commit=settings.git_commit,
        built_at=settings.built_at,
    )
