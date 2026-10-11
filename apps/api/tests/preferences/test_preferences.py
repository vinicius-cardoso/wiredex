"""A workspace's settings (24-minimum-stock): the defaults for one that never saved any, a
choice saved once, and the wire.
"""

from types import TracebackType
from typing import Self, get_args
from uuid import uuid7

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from wiredex.preferences.api.router import PreferencesUseCases, create_router
from wiredex.preferences.api.schemas import StockBasisName
from wiredex.preferences.application.preferences import GetPreferences, UpdatePreferences
from wiredex.preferences.domain.preferences import (
    PreferencesError,
    StockBasis,
    WorkspaceId,
    WorkspacePreferences,
)

BENCH = WorkspaceId(uuid7())
OTHER = WorkspaceId(uuid7())


class InMemoryPreferences:
    """Every workspace's saved choices, and a unit of work scoped to one of them."""

    def __init__(self) -> None:
        self.saved: dict[WorkspaceId, WorkspacePreferences] = {}
        self.commits = 0

    def for_workspace(self, workspace_id: WorkspaceId) -> Scoped:
        return Scoped(self, workspace_id)


class Scoped:
    def __init__(self, store: InMemoryPreferences, workspace_id: WorkspaceId) -> None:
        self._store = store
        self._workspace_id = workspace_id
        self.preferences = self

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    async def get(self) -> WorkspacePreferences | None:
        return self._store.saved.get(self._workspace_id)

    async def add(self, preferences: WorkspacePreferences) -> None:
        self._store.saved[preferences.workspace_id] = preferences

    async def commit(self) -> None:
        self._store.commits += 1


@pytest.fixture
def store() -> InMemoryPreferences:
    return InMemoryPreferences()


def test_a_minimum_is_compared_against_free_stock_unless_the_workspace_says_otherwise() -> None:
    assert WorkspacePreferences.default(BENCH).stock_basis is StockBasis.FREE


def test_the_wire_names_every_basis() -> None:
    assert set(get_args(StockBasisName.__value__)) == {basis.value for basis in StockBasis}


def test_a_basis_that_isnt_one_is_refused_naming_the_options() -> None:
    with pytest.raises(PreferencesError, match="free, total"):
        StockBasis.parse("some")


@pytest.mark.anyio
async def test_reading_the_defaults_saves_nothing(store: InMemoryPreferences) -> None:
    preferences = await GetPreferences(store.for_workspace)(BENCH)

    assert preferences.stock_basis is StockBasis.FREE
    assert store.saved == {}
    assert store.commits == 0


@pytest.mark.anyio
async def test_a_choice_is_saved_once_and_only_for_its_workspace(
    store: InMemoryPreferences,
) -> None:
    update = UpdatePreferences(store.for_workspace)
    get = GetPreferences(store.for_workspace)

    await update(BENCH, StockBasis.TOTAL)
    await update(BENCH, StockBasis.TOTAL)

    assert store.commits == 1
    assert (await get(BENCH)).stock_basis is StockBasis.TOTAL
    assert (await get(OTHER)).stock_basis is StockBasis.FREE
    await update(BENCH, StockBasis.FREE)
    assert store.commits == 2
    assert (await get(BENCH)).stock_basis is StockBasis.FREE


@pytest.mark.anyio
async def test_saving_the_default_for_the_first_time_still_writes_the_row(
    store: InMemoryPreferences,
) -> None:
    await UpdatePreferences(store.for_workspace)(BENCH, StockBasis.FREE)

    assert store.commits == 1
    assert BENCH in store.saved


def test_the_settings_over_http(store: InMemoryPreferences) -> None:
    async def the_bench(_request: Request) -> WorkspaceId:
        return BENCH

    use_cases = PreferencesUseCases(
        GetPreferences(store.for_workspace), UpdatePreferences(store.for_workspace)
    )
    app = FastAPI()
    app.include_router(create_router(use_cases, the_bench), prefix="/api")
    client = TestClient(app)

    assert client.get("/api/preferences").json() == {"stock_basis": "free"}
    saved = client.put("/api/preferences", json={"stock_basis": "total"})
    assert saved.status_code == 200
    assert saved.json() == {"stock_basis": "total"}
    assert client.get("/api/preferences").json() == {"stock_basis": "total"}
    assert client.put("/api/preferences", json={"stock_basis": "some"}).status_code == 422
    assert client.put("/api/preferences", json={}).status_code == 422
