import asyncio
import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4, uuid7

import pytest
from click.testing import CliRunner
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from support.sql import row_counts
from wiredex.bootstrap.cli import cli
from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.inventory import inventory_use_cases
from wiredex.bootstrap.settings import Environment, Settings
from wiredex.inventory.application.intake import QuickAddition, QuickStock
from wiredex.inventory.domain.intake import PartDraft
from wiredex.inventory.domain.values import LocationId, WorkspaceId

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
            " attribute_definitions, part_definitions, files, attachments,"
            " locations, short_code_counters, stock_lots, stock_movements, stock_balances,"
            " units, projects, revisions, bom_lines, bom_designators"
            " CASCADE",
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
    ) == [
        ("Capacitors",),
        ("Consumables",),
        ("Dev boards",),
        ("Integrated circuits",),
        ("Passives",),
        ("Resistors",),
    ]
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


def test_reset_restores_the_sample_inventory_in_demo_benches_only(
    database: str, migrated_database_url: str
) -> None:
    """Requirement 8.6, through the real tables: the sample locations and stock arrive with
    the reset, after the sample parts they point at, and only in a demo bench."""
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

    # The sample tree is back, each location minted a code from WX-L-0001 up.
    assert asyncio.run(
        query(migrated_database_url, "SELECT name, code FROM locations ORDER BY code")
    ) == [
        ("Lab", "WX-L-0001"),
        ("Cabinet A", "WX-L-0002"),
        ("Drawer 3", "WX-L-0003"),
        ("Parts box", "WX-L-0004"),
    ]
    # The sample loose stock is back: the 4k7 resistor split across two locations sums to 180,
    # received into the parts that reset just wrote. The unit-tracked dev boards count through
    # the same ledger too (their own test covers them), so this narrows to the loose parts.
    assert asyncio.run(
        query(
            migrated_database_url,
            "SELECT d.mpn, sum(b.on_hand)::int FROM stock_balances b"
            " JOIN stock_lots l ON l.id = b.lot_id"
            " JOIN part_definitions d ON d.id = l.part_id"
            " WHERE d.mpn IN ('CRCW060310K0FKEA', 'GRM188R71H104KA93D', 'RC0805FR-074K7L')"
            " GROUP BY d.mpn ORDER BY d.mpn",
        )
    ) == [("CRCW060310K0FKEA", 200), ("GRM188R71H104KA93D", 100), ("RC0805FR-074K7L", 180)]
    # The four loose receipts, each with its lot's on_hand agreeing with the ledger it was
    # folded from; the two dev boards add a RECEIVE of 1 apiece, so six RECEIVEs in all.
    assert asyncio.run(
        query(
            migrated_database_url,
            "SELECT count(*) FROM stock_movements WHERE kind = 'RECEIVE'",
        )
    ) == [(6,)]
    # Only the guest's bench: the owner's workspace holds no sample locations or stock, as it
    # holds no sample parts. No reset ever visits a personal workspace.
    for table in ("locations", "stock_lots", "stock_movements", "stock_balances"):
        kinds = f"SELECT DISTINCT w.kind FROM workspaces w JOIN {table} t ON t.workspace_id = w.id"  # noqa: S608
        assert asyncio.run(query(migrated_database_url, kinds)) == [("demo",)]


def test_reset_restores_the_sample_units_in_demo_benches_only(
    database: str, migrated_database_url: str
) -> None:
    """Requirement 7.4, through the real tables: the sample dev boards come back with the
    reset, after the sample stock they ride, minted real codes, and only in a demo bench."""
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

    # The two sample boards are back, each a unit with a canonical MAC, in stock, minted a
    # code from WX-U-0001 up — received into the parts and locations reset just wrote.
    assert asyncio.run(
        query(
            migrated_database_url,
            "SELECT d.mpn, u.code, u.mac, u.status FROM units u"
            " JOIN part_definitions d ON d.id = u.part_id ORDER BY u.code",
        )
    ) == [
        ("ESP32-DEVKITC-32E", "WX-U-0001", "aa:bb:cc:00:11:22", "in_stock"),
        ("SC0915", "WX-U-0002", "aa:bb:cc:00:11:33", "in_stock"),
    ]
    # Each board counts through the ledger: its lot's on_hand equals its one in-stock unit,
    # written as a RECEIVE of 1 alongside the loose stock's four receipts.
    assert asyncio.run(
        query(
            migrated_database_url,
            "SELECT count(*) FROM stock_movements WHERE kind = 'RECEIVE' AND change = 1",
        )
    ) == [(2,)]
    # Only the guest's bench: the owner's workspace holds no sample units, as it holds no
    # sample parts. No reset ever visits a personal workspace.
    assert asyncio.run(
        query(
            migrated_database_url,
            "SELECT DISTINCT w.kind FROM workspaces w JOIN units u ON u.workspace_id = w.id",
        )
    ) == [("demo",)]


def test_reset_puts_back_the_sample_units_a_guest_changed(
    database: str, migrated_database_url: str
) -> None:
    """A second reset restores the units idempotently: a guest who retired and deleted their
    boards finds them back the next morning, numbered from WX-U-0001 again (7.4)."""
    run(database, "demo", "invite", "--email", "guest@example.com")
    run(database, "demo", "reset")
    asyncio.run(query(migrated_database_url, "DELETE FROM units"))

    run(database, "demo", "reset")

    assert asyncio.run(query(migrated_database_url, "SELECT min(code), max(code) FROM units")) == [
        ("WX-U-0001", "WX-U-0002")
    ]


def test_reset_puts_back_the_sample_inventory_a_guest_changed(
    database: str, migrated_database_url: str
) -> None:
    """A second reset restores the inventory idempotently: a guest who cleared their stock and
    locations finds them back the next morning, numbered from WX-L-0001 again (8.6)."""
    run(database, "demo", "invite", "--email", "guest@example.com")
    run(database, "demo", "reset")
    # The guest wipes their inventory clean, in foreign-key order: units point at lots
    # (RESTRICT), so they go before the lots they sit in.
    for table in ("units", "stock_movements", "stock_balances", "stock_lots", "locations"):
        asyncio.run(query(migrated_database_url, f"DELETE FROM {table}"))  # noqa: S608
    asyncio.run(query(migrated_database_url, "DELETE FROM short_code_counters"))

    run(database, "demo", "reset")

    assert asyncio.run(query(migrated_database_url, "SELECT count(*) FROM locations")) == [(4,)]
    # One lot per (part, location): the 4k7 sits in two, so four loose receipts make four
    # lots, and the two dev boards add a lot each — six in all.
    assert asyncio.run(query(migrated_database_url, "SELECT count(*) FROM stock_lots")) == [(6,)]
    # The codes start from WX-L-0001 again: the reset clears the counter so a bench never
    # drifts to WX-L-0005 after a wipe.
    assert asyncio.run(
        query(migrated_database_url, "SELECT min(code), max(code) FROM locations")
    ) == [("WX-L-0001", "WX-L-0004")]
    # The unit codes restart from WX-U-0001 too, off the same cleared counter.
    assert asyncio.run(query(migrated_database_url, "SELECT min(code), max(code) FROM units")) == [
        ("WX-U-0001", "WX-U-0002")
    ]


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
        (10,)
    ]
    assert asyncio.run(
        query(migrated_database_url, "SELECT count(*) FROM categories WHERE name = 'Theirs'")
    ) == [(0,)]


def owner_and_guest(database: str) -> None:
    """The owner's personal workspace and a guest's demo bench, side by side."""
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


SAMPLE_PROJECTS = (
    "SELECT p.name, p.tags, r.label, r.summary, r.status, source.label"
    " FROM projects p JOIN revisions r ON r.project_id = p.id"
    " LEFT JOIN revisions source ON source.id = r.forked_from"
    " ORDER BY p.name, r.label"
)
SAMPLE_PROJECT_ROWS = [
    ("Greenhouse controller", ["esp32", "relay"], "A", "breadboard", "draft", None),
    ("Weather station", ["esp32", "i2c", "outdoor"], "A", "breadboard", "draft", None),
    ("Weather station", ["esp32", "i2c", "outdoor"], "B", "perfboard", "draft", "A"),
]


def test_reset_restores_the_sample_projects_in_demo_benches_only(
    database: str, migrated_database_url: str
) -> None:
    """08's requirements 9.1 and 9.3, through the real tables: the two sample projects with
    their tags and revisions, B forked from A, and only in a demo bench."""
    owner_and_guest(database)

    run(database, "demo", "reset")

    assert asyncio.run(query(migrated_database_url, SAMPLE_PROJECTS)) == SAMPLE_PROJECT_ROWS
    assert asyncio.run(
        query(
            migrated_database_url,
            "SELECT description FROM projects WHERE name = 'Greenhouse controller'",
        )
    ) == [("Waters the tomatoes when the soil dries out.",)]
    # Only the guest's bench: no reset ever visits a personal workspace.
    for table in ("projects", "revisions"):
        kinds = f"SELECT DISTINCT w.kind FROM workspaces w JOIN {table} t ON t.workspace_id = w.id"  # noqa: S608
        assert asyncio.run(query(migrated_database_url, kinds)) == [("demo",)]


def test_reset_puts_back_a_deleted_and_a_renamed_sample_project(
    database: str, migrated_database_url: str
) -> None:
    """08's requirement 9.2: what a guest did to the samples is undone by the next reset."""
    run(database, "demo", "invite", "--email", "guest@example.com")
    run(database, "demo", "reset")
    asyncio.run(
        query(migrated_database_url, "DELETE FROM projects WHERE name = 'Greenhouse controller'")
    )
    asyncio.run(
        query(
            migrated_database_url,
            "UPDATE projects SET name = 'Theirs' WHERE name = 'Weather station'",
        )
    )

    run(database, "demo", "reset")

    assert asyncio.run(query(migrated_database_url, SAMPLE_PROJECTS)) == SAMPLE_PROJECT_ROWS


def test_a_new_guest_finds_the_whole_sample_bench_at_once(
    database: str, migrated_database_url: str
) -> None:
    """No waiting for the nightly reset: the invite itself seeds the new bench with what a
    reset restores, catalog, stock, units and projects (08's requirement 9.4)."""
    run(database, "demo", "invite", "--email", "new-guest@example.com")

    assert asyncio.run(
        query(migrated_database_url, "SELECT name FROM categories ORDER BY name")
    ) == [
        ("Capacitors",),
        ("Consumables",),
        ("Dev boards",),
        ("Integrated circuits",),
        ("Passives",),
        ("Resistors",),
    ]
    assert asyncio.run(query(migrated_database_url, "SELECT count(*) FROM pins")) == [(11,)]
    assert asyncio.run(query(migrated_database_url, "SELECT count(*) FROM locations")) == [(4,)]
    # The four loose receipts and the two boards' receipts of one each.
    assert asyncio.run(
        query(migrated_database_url, "SELECT sum(on_hand)::int FROM stock_balances")
    ) == [(482,)]
    assert asyncio.run(query(migrated_database_url, "SELECT code FROM units ORDER BY code")) == [
        ("WX-U-0001",),
        ("WX-U-0002",),
    ]
    assert asyncio.run(query(migrated_database_url, SAMPLE_PROJECTS)) == SAMPLE_PROJECT_ROWS


SAMPLE_BOMS = (
    "SELECT p.name, r.label, string_agg(d.designator, ' ' ORDER BY d.designator),"
    " part.name, l.quantity, l.notes"
    " FROM bom_lines l JOIN revisions r ON r.id = l.revision_id"
    " JOIN projects p ON p.id = r.project_id"
    " JOIN part_definitions part ON part.id = l.part_id"
    " LEFT JOIN bom_designators d ON d.line_id = l.id"
    " GROUP BY p.name, r.label, l.id, part.name, l.quantity, l.notes, l.created_at"
    " ORDER BY p.name, r.label, l.created_at, l.id"
)
WEATHER_STATION_A = [
    ("U1", "ESP32-DevKitC", 1, None),
    ("U2", "BME280", 1, None),
    ("R1 R2", "Resistor 4k7 0805", 2, "I²C pull-ups"),
    ("C1", "Capacitor 100n 0603 X7R", 1, "BME280 decoupling"),
    (None, "Hook-up wire 22 AWG", 1, "about 2 m of jumpers"),
]
SAMPLE_BOM_ROWS = [
    ("Greenhouse controller", "A", "U1", "ESP32-DevKitC", 1, None),
    (
        "Greenhouse controller",
        "A",
        "R1 R2 R3",
        "Resistor 10k 0603",
        3,
        "soil probe divider and pull-downs",
    ),
    ("Greenhouse controller", "A", "C1", "Capacitor 100n 0603 X7R", 1, None),
    *(("Weather station", "A", *line) for line in WEATHER_STATION_A),
    *(("Weather station", "B", *line) for line in WEATHER_STATION_A),
    ("Weather station", "B", "U3", "AMS1117-3.3", 1, "3V3 from the battery"),
    ("Weather station", "B", "C2 C3", "Capacitor 2u2 0805 X5R", 2, "regulator input and output"),
]


def test_reset_and_invite_restore_the_sample_boms_in_demo_benches_only(
    database: str, migrated_database_url: str
) -> None:
    """09's requirements 10.2 and 10.3, through the real tables: every sample revision's
    lines, B's copied from A by the fork and then extended, pointing at the parts this reset
    wrote; the same after a second reset; and the wire, not stocked, never received."""
    owner_and_guest(database)

    # The invite seeds the bench on its own.
    assert asyncio.run(query(migrated_database_url, SAMPLE_BOMS)) == SAMPLE_BOM_ROWS
    run(database, "demo", "reset")
    first = asyncio.run(query(migrated_database_url, SAMPLE_BOMS))
    run(database, "demo", "reset")

    assert first == SAMPLE_BOM_ROWS
    assert asyncio.run(query(migrated_database_url, SAMPLE_BOMS)) == SAMPLE_BOM_ROWS
    # Only the guest's bench: no reset ever visits a personal workspace.
    for table in ("bom_lines", "bom_designators"):
        kinds = f"SELECT DISTINCT w.kind FROM workspaces w JOIN {table} t ON t.workspace_id = w.id"  # noqa: S608
        assert asyncio.run(query(migrated_database_url, kinds)) == [("demo",)]
    # The wire sits on a BOM and its category is not stocked, so no lot of it exists.
    assert asyncio.run(
        query(
            migrated_database_url,
            "SELECT c.name, c.not_stocked, count(l.id)::int FROM part_definitions d"
            " JOIN categories c ON c.id = d.category_id"
            " LEFT JOIN stock_lots l ON l.part_id = d.id"
            " WHERE d.name = 'Hook-up wire 22 AWG' GROUP BY c.name, c.not_stocked",
        )
    ) == [("Consumables", True, 0)]


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


async def owner_row_counts(owner_url: str) -> dict[str, int]:
    engine = create_async_engine(owner_url)
    try:
        return await row_counts(engine)
    finally:
        await engine.dispose()


async def sample_id(owner_url: str, workspace: UUID, table: str, name: str) -> UUID:
    """A sample row's id in a bench, read as the owner: each reset mints it anew."""
    [(found,)] = await execute(
        owner_url,
        f"SELECT id FROM {table} WHERE workspace_id = :w AND name = :name",  # noqa: S608
        w=workspace,
        name=name,
    )
    assert isinstance(found, UUID)
    return found


async def quick_add_in(app_url: str, owner_url: str, workspace: UUID) -> None:
    """A resistor with a lot and a dev board with two units, each quick-added with its stock
    into the sample *Drawer 3*, as a guest would from the web app: as `wiredex_app`, in one
    intake transaction each."""
    resistors = await sample_id(owner_url, workspace, "categories", "Resistors")
    boards = await sample_id(owner_url, workspace, "categories", "Dev boards")
    drawer = LocationId(await sample_id(owner_url, workspace, "locations", "Drawer 3"))
    engine = create_engine(Settings(environment=Environment.TEST, database_url=SecretStr(app_url)))
    quick_add = inventory_use_cases(create_session_factory(engine)).quick_add
    resistor = PartDraft(
        category_id=resistors, name="Quick resistor 1k", attributes={"resistance": "1k"}
    )
    board = PartDraft(category_id=boards, name="Quick board")
    try:
        await quick_add(WorkspaceId(workspace), QuickAddition(resistor, QuickStock(drawer, 100)))
        await quick_add(WorkspaceId(workspace), QuickAddition(board, QuickStock(drawer, 2)))
    finally:
        await engine.dispose()


def test_reset_clears_what_quick_add_wrote_in_a_demo_bench(
    database: str, migrated_database_url: str
) -> None:
    """Requirement 10.5: a guest's quick-adds are changes like any other. The next reset clears
    their parts, lots, movements, balances and units, and restores the sample data it always
    has, with nothing of intake's own."""
    run(database, "demo", "invite", "--email", "guest@example.com")
    run(database, "demo", "reset")
    sample = asyncio.run(owner_row_counts(migrated_database_url))
    [(bench,)] = asyncio.run(query(migrated_database_url, "SELECT id FROM workspaces"))
    assert isinstance(bench, UUID)
    asyncio.run(quick_add_in(database, migrated_database_url, bench))
    quick = "SELECT count(*) FROM part_definitions WHERE name LIKE 'Quick %'"
    assert asyncio.run(query(migrated_database_url, quick)) == [(2,)]
    # The sample's two boards and the two just received.
    assert asyncio.run(query(migrated_database_url, "SELECT count(*) FROM units")) == [(4,)]

    run(database, "demo", "reset")

    assert asyncio.run(query(migrated_database_url, quick)) == [(0,)]
    # Every table as the first reset left it: the sample and nothing more.
    assert asyncio.run(owner_row_counts(migrated_database_url)) == sample
