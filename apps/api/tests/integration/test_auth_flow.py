import asyncio

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

pytestmark = pytest.mark.integration

LOGIN = {"email": "owner@example.com", "password": "correct horse battery"}


async def _create_owner(settings: Settings) -> None:
    async with create_account_use_case(settings) as create_account:
        await create_account(
            NewAccount(Email(LOGIN["email"]), Name("Owner"), Password(LOGIN["password"]))
        )


async def _stored_session_values(database_url: str) -> list[str]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            rows = await connection.execute(text("SELECT token_hash, device FROM sessions"))
            return [value for row in rows for value in row]
    finally:
        await engine.dispose()


async def _clean(database_url: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("TRUNCATE users, workspaces, memberships, sessions CASCADE")
            )
    finally:
        await engine.dispose()


def test_log_in_see_yourself_and_log_out_against_postgres(migrated_database_url: str) -> None:
    settings = Settings(environment=Environment.TEST, database_url=SecretStr(migrated_database_url))
    asyncio.run(_create_owner(settings))
    try:
        with TestClient(create_app(settings), base_url="https://testserver") as client:
            login = client.post("/api/auth/login", json=LOGIN, headers={"User-Agent": "pytest"})
            assert login.status_code == 200, login.text

            assert client.get("/api/auth/me").json()["email"] == LOGIN["email"]

            stored = asyncio.run(_stored_session_values(migrated_database_url))
            token = client.cookies["__Host-wiredex_session"]
            assert "pytest" in stored
            assert token not in stored  # only the SHA-256 of the token is kept

            logout = client.post(
                "/api/auth/logout", headers={CSRF_HEADER: client.cookies[CSRF_COOKIE]}
            )
            assert logout.status_code == 204
            assert client.get("/api/auth/me").status_code == 401
            assert asyncio.run(_stored_session_values(migrated_database_url)) == []
    finally:
        asyncio.run(_clean(migrated_database_url))
