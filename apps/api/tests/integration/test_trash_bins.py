"""The trash's four bins over Postgres, as `wiredex_app` (16-soft-delete-and-trash, task 8).

What only the database can show: one page of the trash across parts, units, projects and
firmware, newest first with each kind's detail, in the same number of statements whatever the
number of records (requirement 10.3); restoring and deleting for good through each bin; emptying;
and another bench's trash unseen, its records a 404 that changes nothing (requirements 8.1, 8.2).
Every record goes to the trash through its own route's delete, as the browser sends it there.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID, uuid7

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from support.sql import counting
from wiredex.bootstrap.catalog import catalog_use_cases
from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.firmware import firmware_use_cases
from wiredex.bootstrap.inventory import inventory_use_cases
from wiredex.bootstrap.projects import projects_use_cases
from wiredex.bootstrap.settings import Environment, Settings
from wiredex.bootstrap.trash import trash_use_cases
from wiredex.catalog.application.categories import NewCategory
from wiredex.catalog.application.parts import NewPart
from wiredex.catalog.domain.part import PartDetails
from wiredex.catalog.domain.values import CategoryId, CategoryName, Manufacturer, Mpn, PartName
from wiredex.catalog.domain.values import WorkspaceId as CatalogWorkspaceId
from wiredex.firmware.domain.firmware import FirmwareDetails
from wiredex.firmware.domain.values import BoardTarget, FirmwareName, Framework
from wiredex.firmware.domain.values import WorkspaceId as FirmwareWorkspaceId
from wiredex.inventory.application.ports import NewLocation
from wiredex.inventory.application.units import NewUnit, UnitReceipt
from wiredex.inventory.domain.values import LocationName, PartId
from wiredex.inventory.domain.values import WorkspaceId as InventoryWorkspaceId
from wiredex.projects.domain.project import ProjectDetails
from wiredex.projects.domain.values import ProjectName
from wiredex.projects.domain.values import WorkspaceId as ProjectsWorkspaceId
from wiredex.trash.api.router import TrashUseCases
from wiredex.trash.domain.errors import TrashItemNotFoundError
from wiredex.trash.domain.trash import TrashKind
from wiredex.trash.domain.values import WorkspaceId

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

MINE = WorkspaceId(uuid7())
THEIRS = WorkspaceId(uuid7())

TABLES = (
    "units, stock_movements, stock_balances, stock_lots, short_code_counters, locations,"
    " pins, part_definitions, attribute_definitions, categories, revisions, projects,"
    " source_files, firmware_versions, firmware_revisions, flashes, firmware"
)

# Each kind's `trashed_at`, read by the owner, whom row-level security doesn't narrow.
TRASHED_AT = {
    TrashKind.PART: text("SELECT trashed_at FROM part_definitions WHERE id = :id"),
    TrashKind.UNIT: text("SELECT trashed_at FROM units WHERE id = :id"),
    TrashKind.PROJECT: text("SELECT trashed_at FROM projects WHERE id = :id"),
    TrashKind.FIRMWARE: text("SELECT trashed_at FROM firmware WHERE id = :id"),
}

type Sessions = async_sessionmaker[AsyncSession]


@pytest.fixture
async def admin(migrated_database_url: str) -> AsyncIterator[AsyncEngine]:
    """The schema owner, which the policies don't apply to: it sees every workspace."""
    engine = create_async_engine(migrated_database_url)
    yield engine
    await engine.dispose()


@pytest.fixture(autouse=True)
async def clean(admin: AsyncEngine) -> AsyncIterator[None]:
    yield
    async with admin.begin() as connection:
        await connection.execute(text(f"TRUNCATE {TABLES} CASCADE"))


@pytest.fixture
async def app(app_database_url: str) -> AsyncIterator[AsyncEngine]:
    """The API's role, with the API's engine: row security applies."""
    settings = Settings(environment=Environment.TEST, database_url=SecretStr(app_database_url))
    engine = create_engine(settings)
    yield engine
    await engine.dispose()


@pytest.fixture
def sessions(app: AsyncEngine) -> Sessions:
    return create_session_factory(app)


@pytest.fixture
def trash(sessions: Sessions) -> TrashUseCases:
    return trash_use_cases(sessions)


@dataclass(frozen=True, slots=True)
class Trashed:
    """One record of each kind a bench moved to the trash, by id."""

    part: UUID
    unit: UUID
    project: UUID
    firmware: UUID

    def of(self, kind: TrashKind) -> UUID:
        return {
            TrashKind.PART: self.part,
            TrashKind.UNIT: self.unit,
            TrashKind.PROJECT: self.project,
            TrashKind.FIRMWARE: self.firmware,
        }[kind]


async def fill(sessions: Sessions, workspace: WorkspaceId, tag: str = "") -> Trashed:
    """A part, a unit, a project and a firmware moved to the trash through their routes' own
    use cases, in that order, so the trash reads them back the other way round. `tag` names a
    second set apart from the first: names, MPNs and categories are unique in a bench."""
    return Trashed(
        part=await a_trashed_part(sessions, workspace, tag),
        unit=await a_trashed_unit(sessions, workspace, tag),
        project=await a_trashed_project(sessions, workspace, tag),
        firmware=await a_trashed_firmware(sessions, workspace, tag),
    )


async def a_category(sessions: Sessions, workspace: WorkspaceId, name: str) -> CategoryId:
    catalog = catalog_use_cases(sessions)
    here = CatalogWorkspaceId(workspace)
    created = await catalog.create_category(here, NewCategory(CategoryName(name)))
    return created.category.id


async def a_trashed_part(sessions: Sessions, workspace: WorkspaceId, tag: str) -> UUID:
    catalog = catalog_use_cases(sessions)
    here = CatalogWorkspaceId(workspace)
    category = await a_category(sessions, workspace, f"Sensors{tag}")
    details = PartDetails(
        PartName(f"BME280 breakout{tag}"), Manufacturer("Bosch"), Mpn(f"BME280{tag}")
    )
    part = await catalog.define_part(here, NewPart(category, details))
    await catalog.delete_part(here, part.id)
    return part.id


async def a_trashed_unit(sessions: Sessions, workspace: WorkspaceId, tag: str) -> UUID:
    """A board received, retired and moved to the trash; its part stays live, to name it."""
    catalog = catalog_use_cases(sessions)
    here = CatalogWorkspaceId(workspace)
    category = await a_category(sessions, workspace, f"Boards{tag}")
    await catalog.set_category_tracking(here, category, True)
    board = await catalog.define_part(
        here, NewPart(category, PartDetails(PartName(f"ESP32-DevKitC{tag}")))
    )
    inventory = inventory_use_cases(sessions)
    shelf = InventoryWorkspaceId(workspace)
    box = await inventory.create_location(shelf, NewLocation(LocationName(f"Box{tag}")))
    received = await inventory.receive_units(
        shelf, UnitReceipt(PartId(board.id), box.id, (NewUnit(),))
    )
    [unit] = received.units
    await inventory.retire_unit(shelf, unit.id)
    await inventory.delete_unit(shelf, unit.id)
    return unit.id


async def a_trashed_project(sessions: Sessions, workspace: WorkspaceId, tag: str) -> UUID:
    projects = projects_use_cases(sessions)
    here = ProjectsWorkspaceId(workspace)
    view = await projects.create_project(here, ProjectDetails(ProjectName(f"Weather station{tag}")))
    await projects.delete_project(here, view.project.id)
    return view.project.id


async def a_trashed_firmware(sessions: Sessions, workspace: WorkspaceId, tag: str) -> UUID:
    firmware = firmware_use_cases(sessions)
    here = FirmwareWorkspaceId(workspace)
    details = FirmwareDetails(
        name=FirmwareName(f"Weather station{tag}"),
        target=BoardTarget("esp32:esp32:esp32"),
        framework=Framework.ARDUINO,
        description=None,
    )
    view = await firmware.create_firmware(here, details)
    await firmware.delete_firmware(here, view.firmware.id)
    return view.firmware.id


async def rows_of(admin: AsyncEngine, kind: TrashKind, record_id: UUID) -> list[object]:
    """The record's `trashed_at`, read by the owner: [] when it is gone for good, [None] when
    it is live, [a time] while it is in the trash."""
    async with admin.connect() as connection:
        found = await connection.execute(TRASHED_AT[kind], {"id": record_id})
        return [row[0] for row in found]


async def test_one_page_lists_every_kind_newest_first_with_its_detail(
    sessions: Sessions, trash: TrashUseCases
) -> None:
    mine = await fill(sessions, MINE)

    page = await trash.list_trash(MINE, None, 50)

    assert [(item.kind, item.id) for item in page.items] == [
        (TrashKind.FIRMWARE, mine.firmware),
        (TrashKind.PROJECT, mine.project),
        (TrashKind.UNIT, mine.unit),
        (TrashKind.PART, mine.part),
    ]
    assert [(item.name, item.detail) for item in page.items] == [
        ("Weather station", "esp32:esp32:esp32"),
        ("Weather station", None),
        ("WX-U-0001", "ESP32-DevKitC"),
        ("BME280 breakout", "BME280"),
    ]
    assert page.next is None


async def test_a_page_costs_the_same_statements_whatever_the_records(
    app: AsyncEngine, sessions: Sessions, trash: TrashUseCases
) -> None:
    # Requirement 10.3: one read per bin, and the units' parts in one more, never one per row.
    await fill(sessions, MINE)
    with counting(app) as one_each:
        first = await trash.list_trash(MINE, None, 50)
    await fill(sessions, MINE, "-2")
    with counting(app) as two_each:
        second = await trash.list_trash(MINE, None, 50)

    assert (len(first.items), len(second.items)) == (4, 8)
    assert len(one_each) == len(two_each)


async def test_the_cursor_reads_the_next_page_across_kinds(
    sessions: Sessions, trash: TrashUseCases
) -> None:
    mine = await fill(sessions, MINE)

    first = await trash.list_trash(MINE, None, 3)
    assert first.next is not None
    second = await trash.list_trash(MINE, first.next, 3)

    assert [item.id for item in first.items] == [mine.firmware, mine.project, mine.unit]
    assert [item.id for item in second.items] == [mine.part]
    assert second.next is None


@pytest.mark.parametrize("kind", list(TrashKind))
async def test_each_bin_restores_its_record(
    admin: AsyncEngine, sessions: Sessions, trash: TrashUseCases, kind: TrashKind
) -> None:
    # Requirements 5.1 and 5.3: live again, out of the trash, and a second restore a 404.
    mine = await fill(sessions, MINE)
    record = mine.of(kind)

    await trash.restore_from_trash(MINE, kind, record)

    assert await rows_of(admin, kind, record) == [None]
    page = await trash.list_trash(MINE, None, 50)
    assert record not in {item.id for item in page.items}
    assert len(page.items) == 3
    with pytest.raises(TrashItemNotFoundError):
        await trash.restore_from_trash(MINE, kind, record)


@pytest.mark.parametrize("kind", list(TrashKind))
async def test_each_bin_deletes_its_record_for_good(
    admin: AsyncEngine, sessions: Sessions, trash: TrashUseCases, kind: TrashKind
) -> None:
    # Requirements 6.1 and 6.2: gone, and a second delete for good a 404.
    mine = await fill(sessions, MINE)
    record = mine.of(kind)

    await trash.delete_from_trash(MINE, kind, record)

    assert await rows_of(admin, kind, record) == []
    with pytest.raises(TrashItemNotFoundError):
        await trash.delete_from_trash(MINE, kind, record)
    assert len((await trash.list_trash(MINE, None, 50)).items) == 3


async def test_a_live_record_is_not_in_the_trash(
    admin: AsyncEngine, sessions: Sessions, trash: TrashUseCases
) -> None:
    mine = await fill(sessions, MINE)
    await trash.restore_from_trash(MINE, TrashKind.PROJECT, mine.project)

    with pytest.raises(TrashItemNotFoundError):
        await trash.delete_from_trash(MINE, TrashKind.PROJECT, mine.project)
    assert await rows_of(admin, TrashKind.PROJECT, mine.project) == [None]


async def test_another_benchs_trash_is_unseen_and_untouched(
    admin: AsyncEngine, sessions: Sessions, trash: TrashUseCases
) -> None:
    # Requirements 8.1 and 8.2, as wiredex_app: their records aren't listed, restoring or
    # deleting one by its id is a 404, and emptying my trash leaves theirs whole.
    mine = await fill(sessions, MINE)
    theirs = await fill(sessions, THEIRS)

    page = await trash.list_trash(MINE, None, 50)
    assert {item.id for item in page.items} == {mine.of(kind) for kind in TrashKind}
    for kind in TrashKind:
        with pytest.raises(TrashItemNotFoundError):
            await trash.restore_from_trash(MINE, kind, theirs.of(kind))
        with pytest.raises(TrashItemNotFoundError):
            await trash.delete_from_trash(MINE, kind, theirs.of(kind))

    await trash.empty_trash(MINE)

    assert (await trash.list_trash(MINE, None, 50)).items == ()
    for kind in TrashKind:
        assert await rows_of(admin, kind, mine.of(kind)) == []
        [moved] = await rows_of(admin, kind, theirs.of(kind))
        assert moved is not None
    assert len((await trash.list_trash(THEIRS, None, 50)).items) == 4
