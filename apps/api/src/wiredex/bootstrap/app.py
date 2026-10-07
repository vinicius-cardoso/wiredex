from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from functools import partial

from fastapi import FastAPI, Request
from sqlalchemy.ext.asyncio import AsyncEngine

import wiredex
from wiredex.bootstrap.catalog import catalog_use_cases
from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.demo import invite_with_bench
from wiredex.bootstrap.files import create_file_store, files_use_cases
from wiredex.bootstrap.firmware import firmware_use_cases
from wiredex.bootstrap.history import HistoryModules, history_use_cases
from wiredex.bootstrap.identity import session_use_cases
from wiredex.bootstrap.inventory import inventory_use_cases
from wiredex.bootstrap.projects import projects_use_cases
from wiredex.bootstrap.search import search_use_cases
from wiredex.bootstrap.settings import Settings
from wiredex.bootstrap.trash import trash_use_cases
from wiredex.catalog.api.router import CurrentWorkspaceDependency
from wiredex.catalog.api.router import create_router as create_catalog_router
from wiredex.catalog.domain.values import WorkspaceId
from wiredex.files.api.router import CurrentWorkspaceDependency as FilesWorkspaceDependency
from wiredex.files.api.router import create_router as create_files_router
from wiredex.files.domain.values import WorkspaceId as FilesWorkspaceId
from wiredex.firmware.api.router import CurrentWorkspaceDependency as FirmwareWorkspaceDependency
from wiredex.firmware.api.router import create_router as create_firmware_router
from wiredex.firmware.domain.values import WorkspaceId as FirmwareWorkspaceId
from wiredex.history.api.router import CurrentWorkspaceDependency as HistoryWorkspaceDependency
from wiredex.history.api.router import create_router as create_history_router
from wiredex.history.domain.values import WorkspaceId as HistoryWorkspaceId
from wiredex.identity.api.router import SessionUseCases, authenticated_user
from wiredex.identity.api.router import create_router as create_auth_router
from wiredex.identity.application.sessions import CurrentUser
from wiredex.inventory.api.router import CurrentWorkspaceDependency as InventoryWorkspaceDependency
from wiredex.inventory.api.router import create_router as create_inventory_router
from wiredex.inventory.domain.values import WorkspaceId as InventoryWorkspaceId
from wiredex.projects.api.router import CurrentWorkspaceDependency as ProjectsWorkspaceDependency
from wiredex.projects.api.router import create_router as create_projects_router
from wiredex.projects.domain.values import WorkspaceId as ProjectsWorkspaceId
from wiredex.search.api.router import CurrentWorkspaceDependency as SearchWorkspaceDependency
from wiredex.search.api.router import create_router as create_search_router
from wiredex.search.domain.values import WorkspaceId as SearchWorkspaceId
from wiredex.shared_kernel.infrastructure.change_context import Actor, act_as
from wiredex.system.api.router import create_router as create_system_router
from wiredex.system.application.check_readiness import CheckReadiness
from wiredex.system.domain.build_info import BuildInfo
from wiredex.system.infrastructure.sql_database_probe import SqlDatabaseProbe
from wiredex.trash.api.router import CurrentWorkspaceDependency as TrashWorkspaceDependency
from wiredex.trash.api.router import create_router as create_trash_router
from wiredex.trash.domain.values import WorkspaceId as TrashWorkspaceId

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
    auth = session_use_cases(session_factory, partial(invite_with_bench, settings))
    app.include_router(create_auth_router(auth), prefix=API_PREFIX)
    catalog = catalog_use_cases(session_factory)
    app.include_router(create_catalog_router(catalog, _current_workspace(auth)), prefix=API_PREFIX)
    files = files_use_cases(session_factory, create_file_store(settings))
    app.include_router(create_files_router(files, _files_workspace(auth)), prefix=API_PREFIX)
    inventory = inventory_use_cases(session_factory)
    app.include_router(
        create_inventory_router(inventory, _inventory_workspace(auth)), prefix=API_PREFIX
    )
    projects = projects_use_cases(session_factory)
    app.include_router(
        create_projects_router(projects, _projects_workspace(auth)), prefix=API_PREFIX
    )
    firmware = firmware_use_cases(session_factory)
    app.include_router(
        create_firmware_router(firmware, _firmware_workspace(auth)), prefix=API_PREFIX
    )
    trash = trash_use_cases(session_factory)
    app.include_router(create_trash_router(trash, _trash_workspace(auth)), prefix=API_PREFIX)
    modules = HistoryModules(catalog, inventory, projects, firmware, trash)
    history = history_use_cases(session_factory, modules)
    app.include_router(create_history_router(history, _history_workspace(auth)), prefix=API_PREFIX)
    search = search_use_cases(session_factory)
    app.include_router(create_search_router(search, _search_workspace(auth)), prefix=API_PREFIX)
    return app


def _current_workspace(auth: SessionUseCases) -> CurrentWorkspaceDependency:
    """The workspace a request acts in, resolved from its session by identity (ADR 0007).

    Built here because catalog never imports identity: the composition root is the one
    place that knows both, so it hands the catalog router a closure instead (design §3).
    A request with no valid session never reaches a use case — `authenticated_user` raises
    401 first, and an account with no membership is refused the same way.
    """

    async def current_workspace(request: Request) -> WorkspaceId:
        current = await _signed_in(auth, request)
        # Identity's WorkspaceId and the catalog's are the same UUID under two names, one
        # per module: neither module imports the other's domain.
        return WorkspaceId(current.workspace_id)

    return current_workspace


def _files_workspace(auth: SessionUseCases) -> FilesWorkspaceDependency:
    """The same closure the catalog router gets, typed for files' own `WorkspaceId`.

    Files declares its own `WorkspaceId`, as catalog does, so the composition root — the one
    place that imports both — resolves the session once and hands each router the id under
    the name its module knows (design §3). A request with no valid session is refused 401 by
    `authenticated_user` before any files use case runs.
    """

    async def current_workspace(request: Request) -> FilesWorkspaceId:
        current = await _signed_in(auth, request)
        return FilesWorkspaceId(current.workspace_id)

    return current_workspace


def _inventory_workspace(auth: SessionUseCases) -> InventoryWorkspaceDependency:
    """The same closure the catalog router gets, typed for inventory's own `WorkspaceId`.

    Inventory declares its own `WorkspaceId`, as catalog and files do, so the composition
    root — the one place that imports both — resolves the session once and hands the router
    the id under the name its module knows (design §3). A request with no valid session is
    refused 401 by `authenticated_user` before any inventory use case runs.
    """

    async def current_workspace(request: Request) -> InventoryWorkspaceId:
        current = await _signed_in(auth, request)
        return InventoryWorkspaceId(current.workspace_id)

    return current_workspace


def _projects_workspace(auth: SessionUseCases) -> ProjectsWorkspaceDependency:
    """The same closure the catalog router gets, typed for projects' own `WorkspaceId`.

    Projects declares its own `WorkspaceId`, as every module does, so the composition root
    resolves the session once and hands the router the id under the name its module knows. A
    request with no valid session is refused 401, and a cookie write without the CSRF header
    403, by `authenticated_user` before any projects use case runs (requirements 8.5, 8.6).
    """

    async def current_workspace(request: Request) -> ProjectsWorkspaceId:
        current = await _signed_in(auth, request)
        return ProjectsWorkspaceId(current.workspace_id)

    return current_workspace


def _firmware_workspace(auth: SessionUseCases) -> FirmwareWorkspaceDependency:
    """The same closure the catalog router gets, typed for firmware's own `WorkspaceId`.

    Firmware declares its own `WorkspaceId`, as every module does, so the composition root
    resolves the session once and hands the router the id under the name its module knows. A
    request with no valid session is refused 401, and a cookie write without the CSRF header
    403, by `authenticated_user` before any firmware use case runs (requirements 9.5, 9.6).
    """

    async def current_workspace(request: Request) -> FirmwareWorkspaceId:
        current = await _signed_in(auth, request)
        return FirmwareWorkspaceId(current.workspace_id)

    return current_workspace


def _trash_workspace(auth: SessionUseCases) -> TrashWorkspaceDependency:
    """The same closure the catalog router gets, typed for the trash's own `WorkspaceId`.

    The trash declares its own `WorkspaceId`, as every module does, so the composition root
    resolves the session once and hands the router the id under the name its module knows. A
    request with no valid session is refused 401, and a cookie write without the CSRF header
    403, by `authenticated_user` before any trash use case runs (16's requirements 8.3, 8.4).
    """

    async def current_workspace(request: Request) -> TrashWorkspaceId:
        current = await _signed_in(auth, request)
        return TrashWorkspaceId(current.workspace_id)

    return current_workspace


def _search_workspace(auth: SessionUseCases) -> SearchWorkspaceDependency:
    """The same closure the catalog router gets, typed for the search's own `WorkspaceId`.

    The search declares its own `WorkspaceId`, as every module does, so the composition root
    resolves the session once and hands the router the id under the name its module knows. A
    request with no valid session is refused 401 by `authenticated_user` before any source is
    asked (19's requirement 2.3).
    """

    async def current_workspace(request: Request) -> SearchWorkspaceId:
        current = await _signed_in(auth, request)
        return SearchWorkspaceId(current.workspace_id)

    return current_workspace


def _history_workspace(auth: SessionUseCases) -> HistoryWorkspaceDependency:
    """The same closure the catalog router gets, typed for history's own `WorkspaceId`.

    History declares its own `WorkspaceId`, as every module does, so the composition root
    resolves the session once and hands the router the id under the name its module knows. A
    request with no valid session is refused 401, and a cookie write without the CSRF header
    403, by `authenticated_user` before any history use case runs (17's requirements 6.2, 6.3).
    """

    async def current_workspace(request: Request) -> HistoryWorkspaceId:
        current = await _signed_in(auth, request)
        return HistoryWorkspaceId(current.workspace_id)

    return current_workspace


async def _signed_in(auth: SessionUseCases, request: Request) -> CurrentUser:
    """The caller, authenticated, and every write of this request recorded as theirs.

    Each router's closure comes through here, so the history the database records names the
    signed-in user by the name they have now (17-history, decision 4). A request with no valid
    session is refused 401 by `authenticated_user` before anything is set.
    """
    current = await authenticated_user(auth, request)
    act_as(Actor(current.user.id, current.user.name.value))
    return current


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
