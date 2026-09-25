from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from fastapi import FastAPI, Request
from sqlalchemy.ext.asyncio import AsyncEngine

import wiredex
from wiredex.bootstrap.catalog import catalog_use_cases
from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.identity import session_use_cases
from wiredex.bootstrap.settings import Settings
from wiredex.catalog.api.router import CurrentWorkspaceDependency
from wiredex.catalog.api.router import create_router as create_catalog_router
from wiredex.catalog.domain.values import WorkspaceId
from wiredex.identity.api.router import SessionUseCases, authenticated_user
from wiredex.identity.api.router import create_router as create_auth_router
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
    session_factory = create_session_factory(engine)
    auth = session_use_cases(session_factory)
    app.include_router(create_auth_router(auth), prefix=API_PREFIX)
    catalog = catalog_use_cases(session_factory)
    app.include_router(create_catalog_router(catalog, _current_workspace(auth)), prefix=API_PREFIX)
    return app


def _current_workspace(auth: SessionUseCases) -> CurrentWorkspaceDependency:
    """The workspace a request acts in, resolved from its session by identity (ADR 0007).

    Built here because catalog never imports identity: the composition root is the one
    place that knows both, so it hands the catalog router a closure instead (design §3).
    A request with no valid session never reaches a use case — `authenticated_user` raises
    401 first, and an account with no membership is refused the same way.
    """

    async def current_workspace(request: Request) -> WorkspaceId:
        current = await authenticated_user(auth, request)
        # Identity's WorkspaceId and the catalog's are the same UUID under two names, one
        # per module: neither module imports the other's domain.
        return WorkspaceId(current.workspace_id)

    return current_workspace


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
