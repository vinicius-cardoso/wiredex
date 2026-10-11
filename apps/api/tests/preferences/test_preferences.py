"""A workspace's settings (24-minimum-stock): the defaults for one that never saved any, a
choice saved once, and the wire.
"""

from enum import StrEnum
from types import TracebackType
from typing import Self, TypeAliasType, get_args
from uuid import uuid7

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from wiredex.preferences.api.router import PreferencesUseCases, create_router
from wiredex.preferences.api.schemas import DateFormatName, NumberFormatName, StockBasisName
from wiredex.preferences.application.preferences import GetPreferences, UpdatePreferences
from wiredex.preferences.domain.preferences import (
    Choices,
    DateFormat,
    NumberFormat,
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


@pytest.mark.parametrize(
    ("name", "enum"),
    [(StockBasisName, StockBasis), (DateFormatName, DateFormat), (NumberFormatName, NumberFormat)],
)
def test_the_wire_names_every_option(name: TypeAliasType, enum: type[StrEnum]) -> None:
    assert set(get_args(name.__value__)) == {member.value for member in enum}


@pytest.mark.parametrize(
    ("typed", "kept"), [("WX", "WX"), (" lab ", "LAB"), ("b", "B"), ("ab12cd", "AB12CD")]
)
def test_a_code_prefix_is_kept_in_upper_case(typed: str, kept: str) -> None:
    assert Choices(code_prefix=typed).code_prefix == kept


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

    await update(BENCH, Choices(StockBasis.TOTAL))
    await update(BENCH, Choices(StockBasis.TOTAL))

    assert store.commits == 1
    assert (await get(BENCH)).stock_basis is StockBasis.TOTAL
    assert (await get(OTHER)).stock_basis is StockBasis.FREE
    await update(BENCH, Choices(StockBasis.FREE))
    assert store.commits == 2
    assert (await get(BENCH)).stock_basis is StockBasis.FREE


@pytest.mark.anyio
async def test_saving_the_default_for_the_first_time_still_writes_the_row(
    store: InMemoryPreferences,
) -> None:
    await UpdatePreferences(store.for_workspace)(BENCH, Choices(StockBasis.FREE))

    assert store.commits == 1
    assert BENCH in store.saved


def test_the_settings_over_http(store: InMemoryPreferences) -> None:
    client = _client(store)

    assert client.get("/api/preferences").json() == DEFAULTS
    chosen = {
        "stock_basis": "total",
        "default_minimum_stock": 5,
        "code_prefix": " lab2 ",
        "date_format": "iso",
        "number_format": "comma",
        "trash_retention_days": 30,
    }
    saved = client.put("/api/preferences", json=chosen)
    assert saved.status_code == 200
    assert saved.json() == {**chosen, "code_prefix": "LAB2"}
    assert client.get("/api/preferences").json() == saved.json()
    # What a save leaves out takes its default again: the settings are replaced whole.
    assert client.put("/api/preferences", json={}).json() == DEFAULTS


@pytest.mark.parametrize(
    ("body", "said"),
    [
        ({"stock_basis": "some"}, None),
        ({"date_format": "yyyy"}, None),
        ({"number_format": "space"}, None),
        ({"default_minimum_stock": -1}, None),
        ({"trash_retention_days": 0}, None),
        ({"trash_retention_days": 3651}, None),
        ({"code_prefix": "2WX"}, "a letter followed by up to five letters or digits"),
        ({"code_prefix": "WX-1"}, "a letter followed by up to five letters or digits"),
        ({"code_prefix": "TOOLONG"}, "a letter followed by up to five letters or digits"),
    ],
)
def test_a_choice_that_isnt_one_is_refused_and_nothing_is_saved(
    store: InMemoryPreferences, body: dict[str, object], said: str | None
) -> None:
    client = _client(store)

    refused = client.put("/api/preferences", json=body)

    assert refused.status_code == 422
    if said is not None:
        assert said in refused.json()["detail"]
    assert store.commits == 0


DEFAULTS = {
    "stock_basis": "free",
    "default_minimum_stock": None,
    "code_prefix": "WX",
    "date_format": "language",
    "number_format": "language",
    "trash_retention_days": None,
}


def _client(store: InMemoryPreferences) -> TestClient:
    async def the_bench(_request: Request) -> WorkspaceId:
        return BENCH

    use_cases = PreferencesUseCases(
        GetPreferences(store.for_workspace), UpdatePreferences(store.for_workspace)
    )
    app = FastAPI()
    app.include_router(create_router(use_cases, the_bench), prefix="/api")
    return TestClient(app)
