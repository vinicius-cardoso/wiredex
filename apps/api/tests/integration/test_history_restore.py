"""Restoring a past version over Postgres, as `wiredex_app`, through the modules' own edits
(17-history, task 4).

What only the real wiring can show: each of a part, a unit, a project and a firmware put back as
it was before a change, the restore recorded as a new change by the trigger, with the reason
`restore`; a module refusing values it no longer takes and changing nothing; a move to the trash
restored from the trash, and a 409 once it is gone; another bench's change a 404.
"""

from collections.abc import AsyncIterator
from decimal import Decimal
from uuid import uuid7

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from wiredex.bootstrap.catalog import catalog_use_cases
from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.firmware import firmware_use_cases
from wiredex.bootstrap.history import HistoryModules, history_use_cases
from wiredex.bootstrap.inventory import inventory_use_cases
from wiredex.bootstrap.projects import projects_use_cases
from wiredex.bootstrap.settings import Environment, Settings
from wiredex.bootstrap.trash import trash_use_cases
from wiredex.catalog.application.attributes import NewAttribute
from wiredex.catalog.application.categories import NewCategory
from wiredex.catalog.application.parts import NewPart, PartRevision
from wiredex.catalog.domain.part import PartDetails
from wiredex.catalog.domain.values import (
    AttributeKey,
    AttributeKind,
    AttributeLabel,
    CategoryName,
    Manufacturer,
    Mpn,
    PartName,
    SiValue,
    Unit,
)
from wiredex.catalog.domain.values import WorkspaceId as CatalogWorkspaceId
from wiredex.firmware.domain.firmware import FirmwareDetails
from wiredex.firmware.domain.values import BoardTarget, FirmwareName, Framework
from wiredex.firmware.domain.values import WorkspaceId as FirmwareWorkspaceId
from wiredex.history.api.router import HistoryUseCases
from wiredex.history.domain.errors import (
    ChangeNotFoundError,
    NotRestorableError,
)
from wiredex.history.domain.history import Action, Change, RecordKind
from wiredex.history.domain.values import WorkspaceId
from wiredex.inventory.application.ports import NewLocation
from wiredex.inventory.application.units import NewUnit, UnitReceipt
from wiredex.inventory.domain.values import LocationName, PartId, Serial
from wiredex.inventory.domain.values import WorkspaceId as InventoryWorkspaceId
from wiredex.projects.domain.project import ProjectDetails
from wiredex.projects.domain.values import ProjectName, Tags
from wiredex.projects.domain.values import WorkspaceId as ProjectsWorkspaceId
from wiredex.shared_kernel.domain.paging import PageRequest

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

BENCH = WorkspaceId(uuid7())

TABLES = (
    "history_entries, history_changes, flashes, firmware_revisions, source_files,"
    " firmware_versions, firmware, net_pins, nets, bom_designators, bom_lines, revisions,"
    " projects, units, stock_movements, stock_balances, stock_lots, short_code_counters,"
    " locations, pins, part_definitions, attribute_definitions, categories"
)

type Sessions = async_sessionmaker[AsyncSession]


@pytest.fixture(autouse=True)
async def clean(migrated_database_url: str) -> AsyncIterator[None]:
    yield
    engine = create_async_engine(migrated_database_url)
    async with engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE {TABLES} CASCADE"))
    await engine.dispose()


@pytest.fixture
async def sessions(app_database_url: str) -> AsyncIterator[Sessions]:
    settings = Settings(environment=Environment.TEST, database_url=SecretStr(app_database_url))
    engine = create_engine(settings)
    yield create_session_factory(engine)
    await engine.dispose()


@pytest.fixture
def modules(sessions: Sessions) -> HistoryModules:
    return HistoryModules(
        catalog_use_cases(sessions),
        inventory_use_cases(sessions),
        projects_use_cases(sessions),
        firmware_use_cases(sessions),
        trash_use_cases(sessions),
    )


@pytest.fixture
def history(sessions: Sessions, modules: HistoryModules) -> HistoryUseCases:
    return history_use_cases(sessions, modules)


async def newest(history: HistoryUseCases, kind: RecordKind, record_id: object) -> Change:
    page = await history.list_activity(BENCH, PageRequest(1, 100))
    return next(
        change
        for change in page.items
        if change.record.kind is kind and change.record.id == record_id
    )


async def test_a_parts_edit_is_put_back_and_the_restore_recorded_as_a_new_change(
    modules: HistoryModules, history: HistoryUseCases
) -> None:
    # Requirements 4.1 and 4.2.
    catalog, here = modules.catalog, CatalogWorkspaceId(BENCH)
    created = await catalog.create_category(here, NewCategory(CategoryName("Resistors")))
    resistance = NewAttribute(
        AttributeKey("resistance"), AttributeLabel("Resistance"), AttributeKind.NUMBER, Unit("Ω")
    )
    await catalog.define_attribute(here, created.category.id, resistance)
    details = PartDetails(PartName("R 4k7"), Manufacturer("Yageo"), Mpn("RC0805FR-074K7"))
    part = await catalog.define_part(
        here, NewPart(created.category.id, details, {"resistance": "4k7"})
    )
    edited = PartDetails(PartName("R 10k"), Manufacturer("Yageo"), Mpn("RC0805FR-0710K"))
    await catalog.update_part(here, part.id, PartRevision(edited, {"resistance": "10k"}))
    edit = await newest(history, RecordKind.PART, part.id)

    await history.restore_version(BENCH, edit.id)

    view = await catalog.get_part(here, part.id)
    assert (view.part.name.value, str(view.part.mpn)) == ("R 4k7", "RC0805FR-074K7")
    assert view.part.attributes[AttributeKey("resistance")] == SiValue(Decimal(4700))
    restored = await newest(history, RecordKind.PART, part.id)
    assert restored.id > edit.id
    assert (restored.action, restored.reason) == (Action.RESTORED_VERSION, "restore")
    # The version it replaced stays in history.
    assert edit.id in {
        change.id for change in (await history.list_activity(BENCH, PageRequest())).items
    }


async def test_values_the_schema_no_longer_takes_are_refused_and_nothing_changes(
    modules: HistoryModules, history: HistoryUseCases
) -> None:
    # Requirement 4.4: a required field added since the version.
    catalog, here = modules.catalog, CatalogWorkspaceId(BENCH)
    created = await catalog.create_category(here, NewCategory(CategoryName("Sensors")))
    part = await catalog.define_part(
        here, NewPart(created.category.id, PartDetails(PartName("BME280")))
    )
    await catalog.update_part(here, part.id, PartRevision(PartDetails(PartName("BME280 board"))))
    edit = await newest(history, RecordKind.PART, part.id)
    voltage = NewAttribute(
        AttributeKey("voltage"),
        AttributeLabel("Voltage"),
        AttributeKind.NUMBER,
        Unit("V"),
        required=True,
    )
    await catalog.define_attribute(here, created.category.id, voltage)

    with pytest.raises(NotRestorableError, match="voltage is required"):
        await history.restore_version(BENCH, edit.id)

    assert (await catalog.get_part(here, part.id)).part.name.value == "BME280 board"


async def test_a_units_labels_project_and_firmware_are_put_back_too(
    modules: HistoryModules, history: HistoryUseCases
) -> None:
    catalog, here = modules.catalog, CatalogWorkspaceId(BENCH)
    boards = await catalog.create_category(here, NewCategory(CategoryName("Boards")))
    await catalog.set_category_tracking(here, boards.category.id, True)
    board = await catalog.define_part(
        here, NewPart(boards.category.id, PartDetails(PartName("ESP32-DevKitC")))
    )
    shelf = InventoryWorkspaceId(BENCH)
    box = await modules.inventory.create_location(shelf, NewLocation(LocationName("Box")))
    received = await modules.inventory.receive_units(
        shelf, UnitReceipt(PartId(board.id), box.id, (NewUnit(Serial("SN-1")),))
    )
    [unit] = received.units
    await modules.inventory.relabel_unit(shelf, unit.id, Serial("SN-2"), None)
    projects = ProjectsWorkspaceId(BENCH)
    project = await modules.projects.create_project(
        projects, ProjectDetails(ProjectName("Weather station"), tags=Tags.of(["esp32"]))
    )
    await modules.projects.update_project(
        projects,
        project.project.id,
        ProjectDetails(ProjectName("Station"), tags=Tags.of(["esp32", "i2c"])),
    )
    firmware_here = FirmwareWorkspaceId(BENCH)
    details = FirmwareDetails(
        FirmwareName("Station sketch"), BoardTarget("esp32:esp32:esp32"), Framework.ARDUINO, None
    )
    firmware = await modules.firmware.create_firmware(firmware_here, details)
    moved = FirmwareDetails(
        FirmwareName("Station sketch"), BoardTarget("esp32:esp32:esp32s3"), Framework.ARDUINO, None
    )
    await modules.firmware.update_firmware(firmware_here, firmware.firmware.id, moved)

    for kind, record_id in (
        (RecordKind.UNIT, unit.id),
        (RecordKind.PROJECT, project.project.id),
        (RecordKind.FIRMWARE, firmware.firmware.id),
    ):
        await history.restore_version(BENCH, (await newest(history, kind, record_id)).id)

    assert str((await modules.inventory.get_unit(shelf, unit.id)).serial) == "SN-1"
    restored_project = (await modules.projects.get_project(projects, project.project.id)).project
    assert restored_project.name.value == "Weather station"
    assert [tag.value for tag in restored_project.tags.values] == ["esp32"]
    restored_firmware = await modules.firmware.get_firmware(firmware_here, firmware.firmware.id)
    assert str(restored_firmware.firmware.target) == "esp32:esp32:esp32"


async def test_a_move_to_the_trash_is_restored_from_it_once(
    modules: HistoryModules, history: HistoryUseCases
) -> None:
    # Requirement 4.3.
    projects = ProjectsWorkspaceId(BENCH)
    project = await modules.projects.create_project(
        projects, ProjectDetails(ProjectName("Weather station"))
    )
    await modules.projects.delete_project(projects, project.project.id)
    moved = await newest(history, RecordKind.PROJECT, project.project.id)
    assert moved.action is Action.MOVED_TO_TRASH

    await history.restore_version(BENCH, moved.id)

    view = await modules.projects.get_project(projects, project.project.id)
    assert not view.project.in_trash
    back = await newest(history, RecordKind.PROJECT, project.project.id)
    assert (back.action, back.reason) == (Action.RESTORED_FROM_TRASH, "restore")
    with pytest.raises(NotRestorableError, match="isn't in the trash any more"):
        await history.restore_version(BENCH, moved.id)


async def test_another_benchs_change_is_a_404(
    modules: HistoryModules, history: HistoryUseCases
) -> None:
    # Requirement 4.6.
    projects = ProjectsWorkspaceId(BENCH)
    project = await modules.projects.create_project(
        projects, ProjectDetails(ProjectName("Weather station"))
    )
    await modules.projects.update_project(
        projects, project.project.id, ProjectDetails(ProjectName("Station"))
    )
    edit = await newest(history, RecordKind.PROJECT, project.project.id)

    with pytest.raises(ChangeNotFoundError):
        await history.restore_version(WorkspaceId(uuid7()), edit.id)

    view = await modules.projects.get_project(projects, project.project.id)
    assert view.project.name.value == "Station"
