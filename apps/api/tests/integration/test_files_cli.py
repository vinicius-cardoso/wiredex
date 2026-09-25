"""`wiredex files prune` end to end: the nightly sweep against a real database and store.

Requirement 4.4, through the CLI a systemd timer runs (ADR 0011): across every workspace,
an attachment whose part is gone is dropped, a file row no attachment uses is dropped, and a
stored object no row names is deleted, while an attachment on a surviving part and its file
are left untouched. The store is a `LocalFileStore` in a temporary folder, the shape a
production deployment mirrors on the bucket.
"""

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4, uuid7

import pytest
from click.testing import CliRunner
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from wiredex.bootstrap.cli import cli

pytestmark = pytest.mark.integration

NOW = datetime(2026, 9, 25, 10, tzinfo=UTC)


def run(
    database_url: str, files_dir: Path, *arguments: str, standard_input: str | None = None
) -> str:
    result = CliRunner().invoke(
        cli,
        list(arguments),
        input=standard_input,
        env={
            "WIREDEX_DATABASE_URL": database_url,
            "WIREDEX_FILE_STORE": "local",
            "WIREDEX_FILES_DIR": str(files_dir),
        },
    )
    assert result.exit_code == 0, result.output
    return result.output


async def execute(database_url: str, sql: str, **parameters: object) -> list[tuple[object, ...]]:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            result = await connection.execute(text(sql), parameters)
            return [tuple(row) for row in result] if result.returns_rows else []
    finally:
        await engine.dispose()


@pytest.fixture
def database(migrated_database_url: str, app_database_url: str) -> Iterator[str]:
    """The app role's URL, like production; the tables are emptied afterwards."""
    yield app_database_url
    asyncio.run(
        execute(
            migrated_database_url,
            "TRUNCATE users, workspaces, memberships, sessions, categories,"
            " attribute_definitions, part_definitions, files, attachments CASCADE",
        )
    )


def object_key(workspace_id: UUID, sha256: str) -> str:
    return f"workspaces/{workspace_id}/sha256/{sha256}"


def a_sha(byte: int) -> str:
    """A distinct valid SHA-256 per test file, without hashing real bytes here."""
    return f"{byte:064x}"


async def add_file(url: str, workspace_id: UUID, sha256: str, size: int = 1024) -> None:
    await execute(
        url,
        "INSERT INTO files (workspace_id, sha256, media_type, size, created_at)"
        " VALUES (:workspace_id, :sha256, 'application/pdf', :size, :created_at)",
        workspace_id=workspace_id,
        sha256=sha256,
        size=size,
        created_at=NOW,
    )


async def add_attachment(url: str, workspace_id: UUID, part_id: UUID, sha256: str) -> UUID:
    attachment_id = uuid7()
    await execute(
        url,
        "INSERT INTO attachments"
        " (id, workspace_id, subject_kind, subject_id, sha256, kind, title, created_at)"
        " VALUES (:id, :workspace_id, 'part', :subject_id, :sha256, 'datasheet',"
        " 'Datasheet', :created_at)",
        id=attachment_id,
        workspace_id=workspace_id,
        subject_id=part_id,
        sha256=sha256,
        created_at=NOW,
    )
    return attachment_id


async def a_demo_bench(url: str) -> tuple[UUID, UUID]:
    """The demo bench a fresh invite seeds, and the id of one of its sample parts."""
    [(workspace_id,)] = await execute(url, "SELECT id FROM workspaces WHERE kind = 'demo'")
    [(part_id,)] = await execute(
        url, "SELECT id FROM part_definitions WHERE workspace_id = :w LIMIT 1", w=workspace_id
    )
    assert isinstance(workspace_id, UUID)
    assert isinstance(part_id, UUID)
    return workspace_id, part_id


def write_object(files_dir: Path, workspace_id: UUID, sha256: str, data: bytes) -> Path:
    path = files_dir / object_key(workspace_id, sha256)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_prune_removes_orphans_and_keeps_what_a_live_part_uses(
    database: str, migrated_database_url: str, tmp_path: Path
) -> None:
    run(database, tmp_path, "demo", "invite", "--email", "guest@example.com")
    workspace_id, live_part = asyncio.run(a_demo_bench(migrated_database_url))
    gone_part = uuid4()  # never in part_definitions: a deleted part's subject

    kept_sha, orphan_attachment_sha, unused_sha = a_sha(1), a_sha(2), a_sha(3)
    for sha in (kept_sha, orphan_attachment_sha, unused_sha):
        asyncio.run(add_file(migrated_database_url, workspace_id, sha))
        write_object(tmp_path, workspace_id, sha, b"bytes")
    # A stray object no row ever named, from a torn upload the sweep must still catch.
    stray = write_object(tmp_path, workspace_id, a_sha(9), b"stray")
    # Kept: its part is alive. Orphaned: its part is gone. The unused file has no attachment.
    kept_id = asyncio.run(add_attachment(migrated_database_url, workspace_id, live_part, kept_sha))
    orphan_id = asyncio.run(
        add_attachment(migrated_database_url, workspace_id, gone_part, orphan_attachment_sha)
    )

    output = run(database, tmp_path, "files", "prune")

    assert "Pruned orphaned files in" in output
    # The attachment on the deleted part is gone; the one on the live part remains.
    attachments_left = asyncio.run(
        execute(
            migrated_database_url,
            "SELECT id, sha256 FROM attachments WHERE workspace_id = :w",
            w=workspace_id,
        )
    )
    assert attachments_left == [(kept_id, kept_sha)]
    assert orphan_id not in {row[0] for row in attachments_left}
    # File rows: only the one a surviving attachment uses is left.
    files_left = asyncio.run(
        execute(
            migrated_database_url,
            "SELECT sha256 FROM files WHERE workspace_id = :w",
            w=workspace_id,
        )
    )
    assert files_left == [(kept_sha,)]
    # Objects: the kept file's stays, every orphan and the stray are gone.
    assert (tmp_path / object_key(workspace_id, kept_sha)).exists()
    for sha in (orphan_attachment_sha, unused_sha):
        assert not (tmp_path / object_key(workspace_id, sha)).exists()
    assert not stray.exists()


def test_prune_reaches_every_workspace(
    database: str, migrated_database_url: str, tmp_path: Path
) -> None:
    """Not only demo benches: an orphan in the owner's personal workspace is swept too."""
    run(
        database,
        tmp_path,
        "users",
        "create",
        "--email",
        "owner@example.com",
        "--name",
        "Owner",
        "--password-stdin",
        standard_input="correct horse battery\n",
    )
    [(owner_workspace,)] = asyncio.run(
        execute(migrated_database_url, "SELECT id FROM workspaces WHERE kind = 'personal'")
    )
    assert isinstance(owner_workspace, UUID)
    unused = a_sha(1)
    asyncio.run(add_file(migrated_database_url, owner_workspace, unused))
    write_object(tmp_path, owner_workspace, unused, b"bytes")

    run(database, tmp_path, "files", "prune")

    assert asyncio.run(
        execute(
            migrated_database_url,
            "SELECT count(*) FROM files WHERE workspace_id = :w",
            w=owner_workspace,
        )
    ) == [(0,)]
    assert not (tmp_path / object_key(owner_workspace, unused)).exists()
