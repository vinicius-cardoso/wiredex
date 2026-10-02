"""History recorded by the database, as the API's role writes (17-history, task 2).

What only Postgres can show: every tracked table's rows recorded under the record they belong to,
in the writer's transaction; one change per transaction and record; the no-ops and the cascades
left out; who and why read from the transaction's settings; and history that the API's role can
read and delete but never write.
"""

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid7

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from wiredex.bootstrap.database import create_engine
from wiredex.bootstrap.settings import Environment, Settings
from wiredex.shared_kernel.infrastructure.change_context import Actor
from wiredex.shared_kernel.infrastructure.history_tracking import TRACKED_TABLES
from wiredex.shared_kernel.infrastructure.row_security import name_the_transaction

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

OWNER = Actor(uuid7(), "Owner")

TABLES = (
    "history_entries, history_changes, flashes, firmware_revisions, source_files,"
    " firmware_versions, firmware, net_pins, nets, bom_designators, bom_lines, revisions,"
    " projects, units, stock_lots, locations, attachments, files, pins, part_definitions,"
    " attribute_definitions, categories"
)

# One row of every tracked table, each in the record it belongs to, as plain SQL: the trigger is
# the subject here, not the modules that write these rows.
BENCH = (
    "INSERT INTO categories (id, workspace_id, parent_id, name, created_at,"
    " tracked_individually, not_stocked) VALUES (:category, :w, NULL, 'Sensors', now(), false,"
    " false)",
    "INSERT INTO attribute_definitions (id, workspace_id, category_id, key, label, kind, unit,"
    " required, options, position, created_at) VALUES (:attribute, :w, :category, 'pressure',"
    " 'Pressure', 'number', 'Pa', false, '[]', 0, now())",
    "INSERT INTO part_definitions (id, workspace_id, category_id, name, attributes, created_at,"
    " updated_at) VALUES (:part, :w, :category, 'BME280 breakout', '{}', now(), now())",
    "INSERT INTO pins (workspace_id, part_id, number, position, label, type, functions)"
    " VALUES (:w, :part, '3', 0, 'SDA', 'io', '{}')",
    "INSERT INTO files (workspace_id, sha256, media_type, size, created_at)"
    " VALUES (:w, repeat('a', 64), 'application/pdf', 10, now())",
    "INSERT INTO attachments (id, workspace_id, subject_kind, subject_id, sha256, kind, title,"
    " created_at) VALUES (:attachment, :w, 'part', :part, repeat('a', 64), 'datasheet',"
    " 'BME280 datasheet', now())",
    "INSERT INTO locations (id, workspace_id, parent_id, code, name, created_at)"
    " VALUES (:location, :w, NULL, 'WX-L-9001', 'Drawer', now())",
    "INSERT INTO stock_lots (id, workspace_id, part_id, location_id, created_at)"
    " VALUES (:lot, :w, :part, :location, now())",
    "INSERT INTO units (id, workspace_id, part_id, lot_id, code, serial, mac, status,"
    " created_at, revision_id) VALUES (:unit, :w, :part, :lot, 'WX-U-9001', NULL, NULL,"
    " 'in_stock', now(), NULL)",
    "INSERT INTO projects (id, workspace_id, name, description, tags, created_at, updated_at)"
    " VALUES (:project, :w, 'Weather station', NULL, '{}', now(), now())",
    "INSERT INTO revisions (id, workspace_id, project_id, label, summary, notes, status,"
    " forked_from, created_at, updated_at) VALUES (:revision, :w, :project, 'A', NULL, NULL,"
    " 'draft', NULL, now(), now())",
    "INSERT INTO bom_lines (id, workspace_id, revision_id, part_id, quantity, notes, created_at)"
    " VALUES (:line, :w, :revision, :part, 1, NULL, now())",
    "INSERT INTO bom_designators (workspace_id, revision_id, designator, line_id)"
    " VALUES (:w, :revision, 'U1', :line)",
    "INSERT INTO nets (id, workspace_id, revision_id, name, color, notes, created_at)"
    " VALUES (:net, :w, :revision, 'SDA', 'blue', NULL, now())",
    "INSERT INTO net_pins (workspace_id, net_id, designator, pin, revision_id)"
    " VALUES (:w, :net, 'U1', '3', :revision)",
    "INSERT INTO firmware (id, workspace_id, name, target, framework, description, created_at,"
    " updated_at) VALUES (:firmware, :w, 'Station sketch', 'esp32:esp32:esp32', 'arduino',"
    " NULL, now(), now())",
    "INSERT INTO firmware_versions (id, workspace_id, firmware_id, version, changelog, status,"
    " based_on, created_at, updated_at, released_at) VALUES (:version, :w, :firmware, '1.0.0',"
    " 'First.', 'released', NULL, now(), now(), now())",
    "INSERT INTO source_files (id, workspace_id, version_id, path, content, size)"
    " VALUES (:file, :w, :version, 'station.ino', 'void setup() {}', 15)",
    "INSERT INTO firmware_revisions (workspace_id, firmware_id, revision_id, created_at)"
    " VALUES (:w, :firmware, :revision, now())",
    "INSERT INTO flashes (id, workspace_id, unit_id, unit_code, version_id, revision_id,"
    " flashed_at, notes, created_at) VALUES (:flash, :w, :unit, 'WX-U-9001', :version, NULL,"
    " now(), NULL, now())",
)

_IDS = (
    "category",
    "attribute",
    "part",
    "attachment",
    "location",
    "lot",
    "unit",
    "project",
    "revision",
    "line",
    "net",
    "firmware",
    "version",
    "file",
    "flash",
)


@dataclass(frozen=True, slots=True)
class Bench:
    workspace: UUID
    ids: Mapping[str, UUID]

    def __getitem__(self, name: str) -> UUID:
        return self.ids[name]

    @property
    def parameters(self) -> dict[str, UUID]:
        return {"w": self.workspace, **self.ids}


@pytest.fixture
async def admin(migrated_database_url: str) -> AsyncIterator[AsyncEngine]:
    """The schema owner, which the policies don't apply to: it sees every workspace."""
    engine = create_async_engine(migrated_database_url)
    yield engine
    async with engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE {TABLES} CASCADE"))
    await engine.dispose()


@pytest.fixture
async def app(app_database_url: str) -> AsyncIterator[AsyncEngine]:
    """The API's role, with the API's engine: row security applies."""
    settings = Settings(environment=Environment.TEST, database_url=SecretStr(app_database_url))
    engine = create_engine(settings)
    yield engine
    await engine.dispose()


def a_bench() -> Bench:
    return Bench(uuid7(), {name: uuid7() for name in _IDS})


async def write(
    engine: AsyncEngine,
    bench: Bench,
    *statements: str,
    actor: Actor | None = OWNER,
    reason: str | None = None,
) -> None:
    """The statements in one transaction of the bench's, named as the API names its own."""
    async with AsyncSession(engine) as session, session.begin():
        await name_the_transaction(session, bench.workspace, actor, reason)
        for statement in statements:
            await session.execute(text(statement), bench.parameters)


async def changes_of(admin: AsyncEngine, bench: Bench) -> list[dict[str, Any]]:
    """The bench's changes in order, each with its rows' tables and operations in order."""
    async with admin.connect() as connection:
        rows = await connection.execute(
            text(
                "SELECT c.id, c.root_kind, c.root_id, c.root_label, c.actor_id, c.actor_name,"
                " c.reason, c.entry_count, array_agg(e.table_name || ':' || e.operation"
                " ORDER BY e.id) AS rows, array_agg(array_to_string(e.changed, ',') ORDER BY e.id)"
                " AS changed,"
                " bool_or(e.own) AS has_own"
                " FROM history_changes c JOIN history_entries e ON e.change_id = c.id"
                " WHERE c.workspace_id = :w GROUP BY c.id ORDER BY c.id"
            ),
            {"w": bench.workspace},
        )
        return [dict(row._mapping) for row in rows]


async def test_every_tracked_table_is_recorded_under_the_record_it_belongs_to(
    admin: AsyncEngine, app: AsyncEngine
) -> None:
    # Requirements 1.1 and 1.2: one change per record of the transaction, each of its rows in it.
    bench = a_bench()
    await write(app, bench, *BENCH)

    recorded = {
        (change["root_kind"], change["root_label"]): change["rows"]
        for change in await changes_of(admin, bench)
    }

    assert recorded == {
        ("category", "Sensors"): ["categories:insert", "attribute_definitions:insert"],
        ("part", "BME280 breakout"): [
            "part_definitions:insert",
            "pins:insert",
            "attachments:insert",
        ],
        ("location", "Drawer"): ["locations:insert"],
        ("unit", "WX-U-9001"): ["units:insert", "flashes:insert"],
        ("project", "Weather station"): [
            "projects:insert",
            "revisions:insert",
            "bom_lines:insert",
            "bom_designators:insert",
            "nets:insert",
            "net_pins:insert",
        ],
        ("firmware", "Station sketch"): [
            "firmware:insert",
            "firmware_versions:insert",
            "source_files:insert",
            "firmware_revisions:insert",
        ],
    }
    # The ledger's own tables and files are not tracked (decision 2).
    assert all("stock_lots:insert" not in rows for rows in recorded.values())


async def test_the_triggers_are_on_exactly_the_tracked_tables(admin: AsyncEngine) -> None:
    async with admin.connect() as connection:
        tables = await connection.scalars(
            text(
                "SELECT DISTINCT c.relname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid"
                " WHERE t.tgname = 'record_history' AND NOT t.tgisinternal"
            )
        )
        assert set(tables) == set(TRACKED_TABLES)


async def test_an_attachment_of_a_revision_belongs_to_its_project(
    admin: AsyncEngine, app: AsyncEngine
) -> None:
    bench = a_bench()
    await write(app, bench, *BENCH)
    await write(
        app,
        bench,
        "INSERT INTO attachments (id, workspace_id, subject_kind, subject_id, sha256, kind,"
        " title, created_at) VALUES (gen_random_uuid(), :w, 'revision', :revision,"
        " repeat('a', 64), 'schematic', 'Schematic', now())",
    )

    last = (await changes_of(admin, bench))[-1]

    assert (last["root_kind"], last["root_id"], last["rows"]) == (
        "project",
        bench["project"],
        ["attachments:insert"],
    )
    assert last["has_own"] is False


async def test_an_update_lists_what_changed_and_no_ops_record_nothing(
    admin: AsyncEngine, app: AsyncEngine
) -> None:
    # Requirement 1.3: unchanged, or only `updated_at`, is nothing.
    bench = a_bench()
    await write(app, bench, *BENCH)
    before = len(await changes_of(admin, bench))
    await write(app, bench, "UPDATE part_definitions SET name = name WHERE id = :part")
    await write(
        app,
        bench,
        "UPDATE part_definitions SET updated_at = now() + interval '1 hour' WHERE id = :part",
    )
    assert len(await changes_of(admin, bench)) == before

    await write(
        app,
        bench,
        "UPDATE part_definitions SET name = 'BME280', mpn = 'BME280' WHERE id = :part",
    )

    last = (await changes_of(admin, bench))[-1]
    assert last["rows"] == ["part_definitions:update"]
    assert last["changed"] == ["mpn,name"]
    assert last["root_label"] == "BME280"


async def test_a_rolled_back_write_records_nothing(admin: AsyncEngine, app: AsyncEngine) -> None:
    # Requirement 1.4.
    bench = a_bench()
    await write(app, bench, *BENCH)
    before = await changes_of(admin, bench)

    with pytest.raises(DBAPIError):
        await write(
            app,
            bench,
            "UPDATE part_definitions SET name = 'Renamed' WHERE id = :part",
            "INSERT INTO categories (id) VALUES (NULL)",
        )

    assert await changes_of(admin, bench) == before


async def test_a_record_deleted_with_what_it_holds_is_recorded_once(
    admin: AsyncEngine, app: AsyncEngine
) -> None:
    # Requirement 1.5: its revision, line, designator, net, net pin and runs-on link go with it,
    # and only the project's own deletion is listed.
    bench = a_bench()
    await write(app, bench, *BENCH)
    await write(
        app,
        bench,
        "DELETE FROM firmware_revisions WHERE revision_id = :revision",
        "DELETE FROM projects WHERE id = :project",
    )

    deletions = (await changes_of(admin, bench))[-2:]

    assert {(change["root_kind"], tuple(change["rows"])) for change in deletions} == {
        ("firmware", ("firmware_revisions:delete",)),
        ("project", ("projects:delete",)),
    }


async def test_the_transaction_names_who_and_why(admin: AsyncEngine, app: AsyncEngine) -> None:
    # Requirements 1.2 and 1.6: the user and the reason from the transaction's settings, and
    # none for what Wiredex writes itself.
    bench = a_bench()
    await write(app, bench, *BENCH)
    await write(
        app,
        bench,
        "UPDATE projects SET name = 'Station' WHERE id = :project",
        reason="restore",
    )
    await write(app, bench, "UPDATE projects SET name = 'Weather' WHERE id = :project", actor=None)

    *_, restored, by_wiredex = await changes_of(admin, bench)

    assert (restored["actor_id"], restored["actor_name"], restored["reason"]) == (
        OWNER.id,
        "Owner",
        "restore",
    )
    assert (by_wiredex["actor_id"], by_wiredex["actor_name"], by_wiredex["reason"]) == (
        None,
        None,
        None,
    )


async def test_each_change_keeps_the_name_its_record_had(
    admin: AsyncEngine, app: AsyncEngine
) -> None:
    # Requirement 1.7.
    bench = a_bench()
    await write(app, bench, *BENCH)
    await write(app, bench, "UPDATE firmware SET name = 'Station' WHERE id = :firmware")
    await write(
        app,
        bench,
        "INSERT INTO source_files (id, workspace_id, version_id, path, content, size)"
        " VALUES (gen_random_uuid(), :w, :version, 'config.h', '', 0)",
    )

    *_, renamed, added = await changes_of(admin, bench)

    assert renamed["root_label"] == "Station"
    assert added["root_label"] == "Station"
    assert (await changes_of(admin, bench))[-3]["root_label"] != "Station"


async def test_the_app_role_reads_and_deletes_its_bench_but_never_writes_history(
    admin: AsyncEngine, app: AsyncEngine
) -> None:
    # Requirements 5.1 and 6.1, and decision 10 of requirements.
    mine, theirs = a_bench(), a_bench()
    await write(app, mine, *BENCH)
    await write(app, theirs, *BENCH)

    async with AsyncSession(app) as session, session.begin():
        await name_the_transaction(session, mine.workspace, OWNER, None)
        seen = await session.scalar(
            text("SELECT count(DISTINCT workspace_id) FROM history_changes")
        )
        assert seen == 1
        entries = await session.scalar(
            text("SELECT count(DISTINCT workspace_id) FROM history_entries")
        )
        assert entries == 1
    for statement in (
        "INSERT INTO history_changes (workspace_id, transaction_id, root_kind, root_id)"
        " VALUES (:w, 1, 'part', :part)",
        "UPDATE history_changes SET actor_name = 'Someone else'",
        "UPDATE history_entries SET after = NULL",
    ):
        with pytest.raises(DBAPIError, match="permission denied"):
            await write(app, mine, statement)

    await write(app, mine, "DELETE FROM history_changes")

    assert await changes_of(admin, mine) == []
    assert len(await changes_of(admin, theirs)) == 6
