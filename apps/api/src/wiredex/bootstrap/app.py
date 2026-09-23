from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

import wiredex
from wiredex.bootstrap.database import create_engine
from wiredex.bootstrap.settings import Settings
from wiredex.system.api.router import create_router as create_system_router
from wiredex.system.application.check_readiness import CheckReadiness
from wiredex.system.domain.build_info import BuildInfo
from wiredex.system.infrastructure.sql_database_probe import SqlDatabaseProbe

API_PREFIX = "/api"

type Lifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application. Uvicorn calls this with `--factory`."""
    settings = settings or Settings()
    engine = create_engine(settings)
    app = FastAPI(
        title="Wiredex API",
        version=wiredex.__version__,
        openapi_url=_docs_path(settings, "/openapi.json"),
        docs_url=_docs_path(settings, "/docs"),
        redoc_url=None,
        lifespan=_lifespan(engine),
    )
    check_readiness = CheckReadiness(SqlDatabaseProbe(engine))
    app.include_router(
        create_system_router(_build_info(settings), check_readiness),
        prefix=API_PREFIX,
    )
    return app


def _lifespan(engine: AsyncEngine) -> Lifespan:
    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        await engine.dispose()

    return lifespan


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
