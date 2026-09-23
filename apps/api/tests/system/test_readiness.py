import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from wiredex.bootstrap.app import create_app
from wiredex.bootstrap.database import create_engine
from wiredex.bootstrap.settings import Environment, Settings
from wiredex.system.api.router import create_router
from wiredex.system.application.check_readiness import CheckReadiness
from wiredex.system.domain.build_info import BuildInfo
from wiredex.system.domain.readiness import Readiness
from wiredex.system.infrastructure.sql_database_probe import SqlDatabaseProbe

# Nothing listens on port 1, so connecting fails immediately.
UNREACHABLE_DATABASE = "postgresql+asyncpg://nobody:nothing@127.0.0.1:1/none"


class FakeDatabaseProbe:
    def __init__(self, *, reachable: bool) -> None:
        self._reachable = reachable

    async def is_reachable(self) -> bool:
        return self._reachable


def client_with(probe: FakeDatabaseProbe) -> TestClient:
    app = FastAPI()
    build_info = BuildInfo(version="0.0.0", commit="unknown")
    app.include_router(create_router(build_info, CheckReadiness(probe)), prefix="/api")
    return TestClient(app)


@pytest.mark.anyio
@pytest.mark.parametrize("reachable", [True, False])
async def test_readiness_follows_the_database(reachable: bool) -> None:
    readiness = await CheckReadiness(FakeDatabaseProbe(reachable=reachable))()

    assert readiness == Readiness(database_reachable=reachable)
    assert readiness.is_ready is reachable


def test_ready_endpoint_answers_200_when_the_database_is_up() -> None:
    response = client_with(FakeDatabaseProbe(reachable=True)).get("/api/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "up"}


def test_ready_endpoint_answers_503_when_the_database_is_down() -> None:
    response = client_with(FakeDatabaseProbe(reachable=False)).get("/api/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "database": "down"}


def test_liveness_ignores_the_database() -> None:
    response = client_with(FakeDatabaseProbe(reachable=False)).get("/api/health")

    assert response.status_code == 200


UNREACHABLE = Settings(environment=Environment.TEST, database_url=SecretStr(UNREACHABLE_DATABASE))


@pytest.mark.anyio
async def test_sql_probe_reports_an_unreachable_database() -> None:
    engine = create_engine(UNREACHABLE)
    try:
        assert await SqlDatabaseProbe(engine).is_reachable() is False
    finally:
        await engine.dispose()


def test_app_is_not_ready_without_its_database() -> None:
    with TestClient(create_app(UNREACHABLE)) as client:
        assert client.get("/api/health/ready").status_code == 503
