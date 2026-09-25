import asyncio
import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4, uuid7

import pytest
from click.testing import CliRunner
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from wiredex.bootstrap.cli import cli

pytestmark = pytest.mark.integration

RESET_NOW = datetime(2026, 9, 25, 10, tzinfo=UTC)


def run(
    database_url: str,
    *arguments: str,
    standard_input: str | None = None,
    files_dir: Path | None = None,
) -> str:
    env = {"WIREDEX_DATABASE_URL": database_url}
    if files_dir is not None:
        # Keep the reset's ClearWorkspace off the real apps/api/.files folder.
        env |= {"WIREDEX_FILE_STORE": "local", "WIREDEX_FILES_DIR": str(files_dir)}
    result = CliRunner().invoke(cli, list(arguments), input=standard_input, env=env)
    assert result.exit_code == 0, result.output
    return result.output


async def query(database_url: str, sql: str) -> list[tuple[object, ...]]:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            result = await connection.execute(text(sql))
            return [tuple(row) for row in result] if result.returns_rows else []
    finally:
        await engine.dispose()


@pytest.fixture
def database(migrated_database_url: str, app_database_url: str) -> Iterator[str]:
    """The app role's URL, like production; the tables are emptied afterwards."""
    yield app_database_url
    asyncio.run(
        query(
            migrated_database_url,
            "TRUNCATE users, workspaces, memberships, sessions, categories,"
            " attribute_definitions, part_definitions, files, attachments CASCADE",
        )
    )


def test_invite_creates_a_guest_in_a_demo_bench_and_prints_the_password_once(
    database: str,
) -> None:
    output = run(database, "demo", "invite", "--email", "Friend@Example.com", "--expires", "2w")

    assert re.search(r"Invited friend@example.com until \d{4}-\d\d-\d\d \d\d:\d\d UTC", output)
    password = re.search(r"Password, shown only now: (\S+)", output)
    assert password is not None
    assert len(password[1]) == 16
    [(expires_at, kind, role)] = asyncio.run(
        query(
            database,
            "SELECT u.expires_at, w.kind, m.role FROM users u"
            " JOIN memberships m ON m.user_id = u.id JOIN workspaces w ON w.id = m.workspace_id",
        )
    )
    assert (kind, role) == ("demo", "guest")
    assert isinstance(expires_at, datetime)
    assert expires_at - datetime.now(UTC) > timedelta(days=13)


def test_reset_removes_guests_whose_access_ended(database: str, migrated_database_url: str) -> None:
    run(database, "demo", "invite", "--email", "gone@example.com", "--expires", "1h")
    run(database, "demo", "invite", "--email", "still-here@example.com")
    asyncio.run(
        query(
            migrated_database_url,
            "UPDATE users SET expires_at = now() - interval '1 minute'"
            " WHERE email = 'gone@example.com'",
        )
    )

    output = run(database, "demo", "reset")

    assert "Removed 1 expired guest account(s)." in output
    assert asyncio.run(query(database, "SELECT email FROM users")) == [("still-here@example.com",)]
    assert asyncio.run(query(database, "SELECT count(*) FROM workspaces")) == [(1,)]


def test_reset_restores_the_sample_catalog_in_demo_benches_only(
    database: str, migrated_database_url: str
) -> None:
    """The catalog is queried as the schema owner: row-level security hides it otherwise."""
    run(
        database,
        "users",
        "create",
        "--email",
        "owner@example.com",
        "--name",
        "Owner",
        "--password-stdin",
        standard_input="correct horse battery\n",
    )
    run(database, "demo", "invite", "--email", "guest@example.com")

    output = run(database, "demo", "reset")

    assert "Restored the sample catalog of 1 demo workspace(s)." in output
    assert asyncio.run(
        query(migrated_database_url, "SELECT name FROM categories ORDER BY name")
    ) == [("Capacitors",), ("Integrated circuits",), ("Passives",), ("Resistors",)]
    # Only the guest's bench: the owner's workspace is left exactly as it was.
    assert asyncio.run(
        query(
            migrated_database_url,
            "SELECT DISTINCT w.kind FROM workspaces w"
            " JOIN part_definitions p ON p.workspace_id = w.id",
        )
    ) == [("demo",)]
    # 4k7 typed, 4700 stored: compared as a number, so neither side's spelling decides it.
    assert asyncio.run(
        query(
            migrated_database_url,
            "SELECT (attributes->>'resistance')::numeric = 4700 FROM part_definitions"
            " WHERE mpn = 'RC0805FR-074K7L'",
        )
    ) == [(True,)]


def test_reset_restores_the_sample_pinouts_in_demo_benches_only(
    database: str, migrated_database_url: str
) -> None:
    """Requirement 4.3, through the real table: the pins arrive with the sample parts."""
    run(
        database,
        "users",
        "create",
        "--email",
        "owner@example.com",
        "--name",
        "Owner",
        "--password-stdin",
        standard_input="correct horse battery\n",
    )
    run(database, "demo", "invite", "--email", "guest@example.com")

    run(database, "demo", "reset")

    bme280 = (
        "SELECT p.number, p.label FROM pins p JOIN part_definitions d ON d.id = p.part_id"
        " WHERE d.mpn = 'BME280' ORDER BY p.position"
    )
    # Eight pins in the order they were written, two of them labelled GND.
    assert asyncio.run(query(migrated_database_url, bme280)) == [
        ("1", "GND"),
        ("2", "CSB"),
        ("3", "SDI"),
        ("4", "SCK"),
        ("5", "SDO"),
        ("6", "VDDIO"),
        ("7", "GND"),
        ("8", "VDD"),
    ]
    # "SDA MOSI" as an array, and 3V3 as an exact 3.3 in the numeric column.
    assert asyncio.run(
        query(
            migrated_database_url,
            "SELECT p.functions, p.voltage FROM pins p JOIN part_definitions d"
            " ON d.id = p.part_id WHERE d.mpn = 'BME280' AND p.number IN ('3', '8')"
            " ORDER BY p.position",
        )
    ) == [(["SDA", "MOSI"], None), ([], Decimal("3.3"))]
    # Only the guest's bench: the owner's workspace holds no sample pins, as it holds no
    # sample parts.
    assert asyncio.run(
        query(
            migrated_database_url,
            "SELECT DISTINCT w.kind FROM workspaces w JOIN pins p ON p.workspace_id = w.id",
        )
    ) == [("demo",)]


def test_reset_puts_back_what_a_guest_changed(database: str, migrated_database_url: str) -> None:
    run(database, "demo", "invite", "--email", "guest@example.com")
    run(database, "demo", "reset")
    asyncio.run(query(migrated_database_url, "DELETE FROM part_definitions"))
    asyncio.run(
        query(
            migrated_database_url,
            "UPDATE categories SET name = 'Theirs' WHERE name = 'Passives'",
        )
    )

    run(database, "demo", "reset")

    assert asyncio.run(query(migrated_database_url, "SELECT count(*) FROM part_definitions")) == [
        (7,)
    ]
    assert asyncio.run(
        query(migrated_database_url, "SELECT count(*) FROM categories WHERE name = 'Theirs'")
    ) == [(0,)]


def test_a_new_guest_finds_the_sample_catalog_at_once(
    database: str, migrated_database_url: str
) -> None:
    """No waiting for the nightly reset: the invite itself seeds the new bench."""
    run(database, "demo", "invite", "--email", "new-guest@example.com")

    assert asyncio.run(
        query(migrated_database_url, "SELECT name FROM categories ORDER BY name")
    ) == [("Capacitors",), ("Integrated circuits",), ("Passives",), ("Resistors",)]
    assert asyncio.run(query(migrated_database_url, "SELECT count(*) FROM pins")) == [(11,)]


async def execute(database_url: str, sql: str, **parameters: object) -> list[tuple[object, ...]]:
    """Like `query`, but bound parameters, for the file rows a reset must clear."""
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            result = await connection.execute(text(sql), parameters)
            return [tuple(row) for row in result] if result.returns_rows else []
    finally:
        await engine.dispose()


def object_key(workspace_id: UUID, sha256: str) -> str:
    return f"workspaces/{workspace_id}/sha256/{sha256}"


def seed_upload(url: str, files_dir: Path, workspace_id: UUID, sha256: str) -> Path:
    """A file row, an attachment on a fresh part, and the object on disk, as an upload leaves."""
    asyncio.run(
        execute(
            url,
            "INSERT INTO files (workspace_id, sha256, media_type, size, created_at)"
            " VALUES (:w, :sha, 'application/pdf', 1024, :now)",
            w=workspace_id,
            sha=sha256,
            now=RESET_NOW,
        )
    )
    asyncio.run(
        execute(
            url,
            "INSERT INTO attachments"
            " (id, workspace_id, subject_kind, subject_id, sha256, kind, title, created_at)"
            " VALUES (:id, :w, 'part', :part, :sha, 'datasheet', 'Datasheet', :now)",
            id=uuid7(),
            w=workspace_id,
            part=uuid4(),
            sha=sha256,
            now=RESET_NOW,
        )
    )
    path = files_dir / object_key(workspace_id, sha256)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"bytes")
    return path


def test_reset_clears_a_guests_uploads_but_leaves_the_owners(
    database: str, migrated_database_url: str, tmp_path: Path
) -> None:
    """Requirement 5.3: a demo reset wipes the guest bench's files, rows and objects clean,
    and never touches the owner's, whose workspace no reset ever visits."""
    run(
        database,
        "users",
        "create",
        "--email",
        "owner@example.com",
        "--name",
        "Owner",
        "--password-stdin",
        standard_input="correct horse battery\n",
    )
    run(database, "demo", "invite", "--email", "guest@example.com")
    [(guest_workspace,)] = asyncio.run(
        query(migrated_database_url, "SELECT id FROM workspaces WHERE kind = 'demo'")
    )
    [(owner_workspace,)] = asyncio.run(
        query(migrated_database_url, "SELECT id FROM workspaces WHERE kind = 'personal'")
    )
    assert isinstance(guest_workspace, UUID)
    assert isinstance(owner_workspace, UUID)
    guest_object = seed_upload(migrated_database_url, tmp_path, guest_workspace, f"{1:064x}")
    owner_object = seed_upload(migrated_database_url, tmp_path, owner_workspace, f"{2:064x}")

    run(database, "demo", "reset", files_dir=tmp_path)

    # The guest's file row, attachment and object are all gone.
    assert asyncio.run(
        execute(
            migrated_database_url,
            "SELECT count(*) FROM files WHERE workspace_id = :w",
            w=guest_workspace,
        )
    ) == [(0,)]
    assert asyncio.run(
        execute(
            migrated_database_url,
            "SELECT count(*) FROM attachments WHERE workspace_id = :w",
            w=guest_workspace,
        )
    ) == [(0,)]
    assert not guest_object.exists()
    # The owner's are untouched: no reset ever reaches a personal workspace.
    assert asyncio.run(
        execute(
            migrated_database_url,
            "SELECT count(*) FROM files WHERE workspace_id = :w",
            w=owner_workspace,
        )
    ) == [(1,)]
    assert owner_object.exists()
