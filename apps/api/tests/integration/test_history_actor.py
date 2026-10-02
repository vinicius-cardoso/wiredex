"""Who changed what, through the real app (17-history, decision 4): a write sent by a signed-in
user is recorded with their id and name, read from the transaction the composition root named,
and a second request starts with nobody acting until it is authenticated in turn."""

import asyncio
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from wiredex.bootstrap.app import create_app
from wiredex.bootstrap.identity import create_account_use_case
from wiredex.bootstrap.settings import Environment, Settings
from wiredex.identity.api.cookies import CSRF_COOKIE, CSRF_HEADER
from wiredex.identity.application.create_account import NewAccount
from wiredex.identity.domain.values import Email, Name, Password
from wiredex.shared_kernel.infrastructure.change_context import acting

pytestmark = pytest.mark.integration

LOGIN = {"email": "historian@example.com", "password": "correct horse battery"}


async def _create_owner(settings: Settings) -> None:
    async with create_account_use_case(settings) as create_account:
        await create_account(
            NewAccount(Email(LOGIN["email"]), Name("Ada Owner"), Password(LOGIN["password"]))
        )


async def _query(database_url: str, sql: str, **parameters: object) -> list[tuple[object, ...]]:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            result = await connection.execute(text(sql), parameters)
            return [tuple(row) for row in result] if result.returns_rows else []
    finally:
        await engine.dispose()


def test_a_write_through_the_app_is_recorded_as_the_signed_in_users(
    migrated_database_url: str, app_database_url: str
) -> None:
    settings = Settings(environment=Environment.TEST, database_url=SecretStr(app_database_url))
    asyncio.run(_create_owner(settings))
    try:
        with TestClient(create_app(settings), base_url="https://testserver") as client:
            assert client.post("/api/auth/login", json=LOGIN).status_code == 200
            me = client.get("/api/auth/me").json()
            created = client.post(
                "/api/catalog/categories",
                json={"name": "Sensors"},
                headers={CSRF_HEADER: client.cookies[CSRF_COOKIE]},
            )
            assert created.status_code == 201, created.text

        recorded = asyncio.run(
            _query(
                migrated_database_url,
                "SELECT actor_id, actor_name, root_kind, root_label FROM history_changes"
                " WHERE workspace_id = :w",
                w=UUID(me["workspace_id"]),
            )
        )
        assert recorded == [(UUID(me["id"]), "Ada Owner", "category", "Sensors")]
        # The test's own task never acted: each request's actor lives in that request's task.
        assert acting() is None
    finally:
        asyncio.run(
            _query(
                migrated_database_url,
                "TRUNCATE history_entries, history_changes, categories, users, workspaces,"
                " memberships, sessions CASCADE",
            )
        )
