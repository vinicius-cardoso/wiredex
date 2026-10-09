"""`wiredex firmware build` through the real app and Postgres, with a stand-in compiler
(20-firmware-builds): the requests the command sends are the ones the routes take, a released
version takes the build and lists it, and a draft takes none.
"""

import asyncio
import io
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from wiredex.bootstrap.app import create_app
from wiredex.bootstrap.firmware_build import (
    Api,
    BuildError,
    Request,
    Response,
    Transport,
    build_version,
)
from wiredex.bootstrap.identity import create_account_use_case
from wiredex.bootstrap.settings import Environment, Settings
from wiredex.identity.application.create_account import NewAccount
from wiredex.identity.domain.values import Email, Name, Password

pytestmark = pytest.mark.integration

EMAIL, PASSWORD = "builder@example.com", "correct horse battery"
NOW = datetime(2026, 10, 9, 21, 40, tzinfo=UTC)
SKETCH = "void setup() {}\nvoid loop() {}\n"


def through(client: TestClient) -> Transport:
    """The command's requests sent into the app in this process, as `urllib` would send them."""

    def send(request: Request) -> Response:
        answer = client.request(
            request.method, request.path, headers=dict(request.headers), content=request.body
        )
        return Response(answer.status_code, answer.content)

    return send


def compiler(sketch_dir: Path, build_dir: Path, board: str) -> str:
    """What an ESP32 core leaves behind, with the sketch it was given as the app's bytes."""
    (build_dir / "flash_args").write_text(
        "--flash-mode dio\n0x1000 weather.ino.bootloader.bin\n0x10000 weather.ino.bin\n"
    )
    (build_dir / "weather.ino.bootloader.bin").write_bytes(board.encode())
    (build_dir / "weather.ino.bin").write_bytes((sketch_dir / "weather.ino").read_bytes())
    return "arduino-cli 1.4.1"


async def _create_owner(settings: Settings) -> None:
    async with create_account_use_case(settings) as create_account:
        await create_account(NewAccount(Email(EMAIL), Name("Builder"), Password(PASSWORD)))


async def _clean(database_url: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("TRUNCATE users, workspaces CASCADE"))
    finally:
        await engine.dispose()


def test_a_build_is_stored_on_a_released_version_and_refused_on_a_draft(
    migrated_database_url: str, app_database_url: str, tmp_path: Path
) -> None:
    settings = Settings(
        environment=Environment.TEST,
        database_url=SecretStr(app_database_url),
        files_dir=str(tmp_path / "files"),
    )
    asyncio.run(_create_owner(settings))
    try:
        with TestClient(create_app(settings), base_url="https://testserver") as client:
            api = Api(through(client))
            api.log_in(EMAIL, PASSWORD)
            bearer = {"Authorization": f"Bearer {api._token}"}
            created = client.post(
                "/api/firmware",
                headers=bearer,
                json={"name": "Weather", "target": "esp32:esp32:esp32", "framework": "arduino"},
            ).json()
            draft = client.post(f"/api/firmware/{created['id']}/versions", headers=bearer, json={})
            version_id = draft.json()["id"]
            files = {"files": [{"path": "weather.ino", "content": SKETCH}]}
            client.post(f"/api/firmware/versions/{version_id}/files", headers=bearer, json=files)
            client.patch(
                f"/api/firmware/versions/{version_id}",
                headers=bearer,
                json={"version": "1.0.0", "changelog": "First light."},
            )

            # A draft takes no build: the command says so, and the route does too.
            (tmp_path / "draft").mkdir()
            with pytest.raises(BuildError, match="is a draft"):
                build_version(
                    api, compiler, name="Weather", number="1.0.0",
                    workdir=tmp_path / "draft", now=lambda: NOW,
                )  # fmt: skip
            with pytest.raises(BuildError, match="that firmware version doesn't exist"):
                api.attach_build(version_id, "Too early", b"PK\x03\x04draft")

            released = client.post(f"/api/firmware/versions/{version_id}/release", headers=bearer)
            assert released.status_code == 200, released.text
            (tmp_path / "work").mkdir()
            built = build_version(
                api, compiler, name="weather", number="v1.0.0",
                workdir=tmp_path / "work", now=lambda: NOW,
            )  # fmt: skip

            listed = client.get(
                "/api/files/attachments",
                headers=bearer,
                params={"subject": f"firmware_version:{version_id}"},
            ).json()
            assert [(one["kind"], one["title"], one["media_type"]) for one in listed] == [
                ("firmware_build", built.title, "application/zip")
            ]
            content = client.get(listed[0]["content_url"], headers=bearer).content
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                assert archive.read("weather.ino.bin") == SKETCH.encode()
                assert archive.read("weather.ino.bootloader.bin") == b"esp32:esp32:esp32"

            # Not a zip, and not a build: both refused on a version.
            with pytest.raises(BuildError, match="a firmware version takes a build"):
                api.attach_build(version_id, "Notes", b"%PDF-notes")

            api.log_out()
            assert client.get("/api/auth/me", headers=bearer).status_code == 401
    finally:
        asyncio.run(_clean(migrated_database_url))
