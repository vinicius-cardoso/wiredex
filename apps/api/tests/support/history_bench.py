"""One row of every tracked table, written as plain SQL in one transaction of a bench of its
own, for the tests of the history the database records (17-history)."""

from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID, uuid7

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from wiredex.shared_kernel.infrastructure.change_context import Actor
from wiredex.shared_kernel.infrastructure.row_security import name_the_transaction

OWNER = Actor(uuid7(), "Owner")

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
