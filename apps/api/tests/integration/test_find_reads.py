"""Each module's `find` over PostgreSQL, as `wiredex_app` (19-command-palette, decision 1).

What only the database can show: each find is one statement, the titles starting with the text
come first whatever collation the database has, `%`, `_` and `\\` match as typed, and a record in
the trash or of another bench is never answered, row-level security included.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID, uuid7

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from support.sql import counting
from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.firmware import firmware_use_cases
from wiredex.bootstrap.projects import projects_use_cases
from wiredex.bootstrap.settings import Environment, Settings
from wiredex.catalog.domain.category import Category
from wiredex.catalog.domain.part import PartDefinition, PartDetails
from wiredex.catalog.domain.schema import AttributeValues
from wiredex.catalog.domain.values import CategoryId, CategoryName, Mpn, PartDefinitionId, PartName
from wiredex.catalog.domain.values import Manufacturer as CatalogManufacturer
from wiredex.catalog.domain.values import WorkspaceId as CatalogWorkspaceId
from wiredex.catalog.infrastructure.unit_of_work import SqlCatalogUnitOfWork
from wiredex.firmware.domain.firmware import FirmwareDetails
from wiredex.firmware.domain.values import BoardTarget, FirmwareId, FirmwareName, Framework
from wiredex.firmware.domain.values import WorkspaceId as FirmwareWorkspaceId
from wiredex.firmware.infrastructure.unit_of_work import SqlFirmwareUnitOfWork
from wiredex.inventory.domain.location import Location
from wiredex.inventory.domain.lot import StockLot
from wiredex.inventory.domain.unit import Unit, UnitStatus
from wiredex.inventory.domain.values import (
    LocationId,
    LocationName,
    Mac,
    Serial,
    ShortCode,
    StockLotId,
    UnitId,
)
from wiredex.inventory.domain.values import PartId as InventoryPartId
from wiredex.inventory.domain.values import WorkspaceId as InventoryWorkspaceId
from wiredex.inventory.infrastructure.unit_of_work import SqlInventoryUnitOfWork
from wiredex.projects.domain.project import ProjectDetails
from wiredex.projects.domain.values import ProjectId, ProjectName
from wiredex.projects.domain.values import WorkspaceId as ProjectsWorkspaceId
from wiredex.projects.infrastructure.unit_of_work import SqlProjectsUnitOfWork
from wiredex.shared_kernel.infrastructure.ids import Uuid7Generator

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

NOW = datetime(2026, 10, 1, 9, tzinfo=UTC)
BENCH = uuid7()
OTHER = uuid7()
TABLES = (
    "pins, part_definitions, attribute_definitions, categories, units, stock_movements,"
    " stock_balances, stock_lots, short_code_counters, locations, history_entries,"
    " history_changes"
)


@pytest.fixture
async def admin(migrated_database_url: str) -> AsyncIterator[AsyncEngine]:
    """The schema owner, which the policies don't apply to: it sees every bench."""
    engine = create_async_engine(migrated_database_url)
    yield engine
    await engine.dispose()


@pytest.fixture(autouse=True)
async def clean(admin: AsyncEngine) -> AsyncIterator[None]:
    """Emptied by the owner afterwards: the app role is granted no TRUNCATE."""
    yield
    async with admin.begin() as connection:
        await connection.execute(text(f"TRUNCATE {TABLES} CASCADE"))


@pytest.fixture
async def app(app_database_url: str) -> AsyncIterator[AsyncEngine]:
    """The role the API logs in with, which row-level security applies to."""
    settings = Settings(environment=Environment.TEST, database_url=SecretStr(app_database_url))
    engine = create_engine(settings)
    yield engine
    await engine.dispose()


def catalog(app: AsyncEngine, workspace: UUID = BENCH) -> SqlCatalogUnitOfWork:
    return SqlCatalogUnitOfWork(create_session_factory(app), CatalogWorkspaceId(workspace))


async def a_category(app: AsyncEngine, name: str, workspace: UUID = BENCH) -> Category:
    category = Category(
        CategoryId(uuid7()), CatalogWorkspaceId(workspace), None, CategoryName(name), NOW
    )
    async with catalog(app, workspace) as work:
        await work.categories.add(category)
        await work.commit()
    return category


async def parts_in(
    app: AsyncEngine, category: Category, *named: str, mpn: str | None = None
) -> list[PartDefinition]:
    """Parts of the category, by name; the first one carries the MPN when one is given."""
    parts = [
        PartDefinition.define(
            PartDefinitionId(uuid7()),
            category,
            PartDetails(
                PartName(name),
                CatalogManufacturer("Yageo") if mpn and index == 0 else None,
                Mpn(mpn) if mpn and index == 0 else None,
            ),
            AttributeValues(),
            NOW,
        )
        for index, name in enumerate(named)
    ]
    async with catalog(app, category.workspace_id) as work:
        for part in parts:
            await work.parts.add(part)
        await work.commit()
    return parts


class TestCatalog:
    async def test_parts_are_found_in_one_statement_starting_ones_first(
        self, app: AsyncEngine
    ) -> None:
        # Requirements 1.1, 1.3 and 6.1: "res" starts two names, sorted by code point whatever
        # the database's collation ("Resistor" before "resonator"), then the one it is inside.
        passives = await a_category(app, "Passives")
        await parts_in(app, passives, "Pressure sensor", "resonator 16 MHz", "Resistor 10k")
        await parts_in(app, passives, "Thin film", mpn="RES-0805-1K")

        async with catalog(app) as work:
            with counting(app) as statements:
                found = await work.parts.find("res", 10)

        assert len(statements) == 1, statements
        assert [str(part.name) for part in found] == [
            "Resistor 10k",
            "resonator 16 MHz",
            "Pressure sensor",
            "Thin film",
        ]

    async def test_a_find_answers_at_most_its_limit(self, app: AsyncEngine) -> None:
        passives = await a_category(app, "Passives")
        await parts_in(app, passives, *(f"Resistor {index}" for index in range(5)))

        async with catalog(app) as work:
            found = await work.parts.find("resistor", 2)

        assert [str(part.name) for part in found] == ["Resistor 0", "Resistor 1"]

    async def test_wildcards_match_as_typed(self, app: AsyncEngine) -> None:
        # Requirement 1.6: `%`, `_` and `\` are characters, not patterns.
        passives = await a_category(app, "Passives")
        await parts_in(app, passives, "100% tested", "1000 ohm", "a_b", "axb", "back\\slash")

        async with catalog(app) as work:
            percent = await work.parts.find("100%", 10)
            underscore = await work.parts.find("a_b", 10)
            backslash = await work.parts.find("k\\s", 10)

        assert [str(part.name) for part in percent] == ["100% tested"]
        assert [str(part.name) for part in underscore] == ["a_b"]
        assert [str(part.name) for part in backslash] == ["back\\slash"]

    async def test_a_part_in_the_trash_or_of_another_bench_is_never_found(
        self, app: AsyncEngine
    ) -> None:
        # Requirements 2.1 and 2.2.
        passives = await a_category(app, "Passives")
        kept, trashed = await parts_in(app, passives, "Resistor 4k7", "Resistor 10k")
        async with catalog(app) as work:
            gone = await work.parts.get(trashed.id)
            assert gone is not None
            gone.move_to_trash(NOW)
            await work.commit()
        theirs = await a_category(app, "Passives", OTHER)
        await parts_in(app, theirs, "Resistor 1k")

        async with catalog(app) as work:
            found = await work.parts.find("resistor", 10)

        assert [part.id for part in found] == [kept.id]

    async def test_categories_are_found_in_one_statement_starting_ones_first(
        self, app: AsyncEngine
    ) -> None:
        for name in ("Passives", "Sensors", "Boards"):
            await a_category(app, name)
        await a_category(app, "Sensors", OTHER)

        async with catalog(app) as work:
            with counting(app) as statements:
                found = await work.categories.find("s", 10)

        assert len(statements) == 1, statements
        assert [str(category.name) for category in found] == ["Sensors", "Boards", "Passives"]


def inventory(app: AsyncEngine, workspace: UUID = BENCH) -> SqlInventoryUnitOfWork:
    return SqlInventoryUnitOfWork(create_session_factory(app), InventoryWorkspaceId(workspace))


async def locations_named(
    app: AsyncEngine, *named: tuple[str, str], workspace: UUID = BENCH
) -> list[Location]:
    """Root locations, each a (code, name) pair."""
    held = [
        Location(
            LocationId(uuid7()),
            InventoryWorkspaceId(workspace),
            None,
            ShortCode(code),
            LocationName(name),
            NOW,
        )
        for code, name in named
    ]
    async with inventory(app, workspace) as work:
        for location in held:
            await work.locations.add(location)
        await work.commit()
    return held


async def units_coded(
    app: AsyncEngine,
    *codes: str,
    serial: str | None = None,
    mac: str | None = None,
    workspace: UUID = BENCH,
) -> list[Unit]:
    """Units of one part in a fresh lot of a fresh drawer; the first one carries the serial and
    the MAC. The drawer's code takes the first unit's number, so drawers never share one."""
    (drawer,) = await locations_named(
        app, (codes[0].replace("WX-U", "WX-L"), "Drawer"), workspace=workspace
    )
    lot = StockLot(
        StockLotId(uuid7()),
        InventoryWorkspaceId(workspace),
        InventoryPartId(uuid7()),
        drawer.id,
        NOW,
    )
    held = [
        Unit(
            UnitId(uuid7()),
            InventoryWorkspaceId(workspace),
            lot.part_id,
            lot.id,
            ShortCode(code),
            Serial(serial) if serial and index == 0 else None,
            Mac(mac) if mac and index == 0 else None,
            UnitStatus.IN_STOCK,
            NOW,
        )
        for index, code in enumerate(codes)
    ]
    async with inventory(app, workspace) as work:
        await work.lots.add(lot)
        for unit in held:
            await work.units.add(unit)
        await work.commit()
    return held


class TestInventory:
    async def test_units_are_found_by_code_serial_or_mac_in_one_statement(
        self, app: AsyncEngine
    ) -> None:
        # Requirements 1.1, 1.3 and 6.1: the codes starting with the text first, then by code.
        first, _, _ = await units_coded(
            app, "WX-U-0012", "WX-U-0001", "WX-U-0002", serial="SN-12", mac="02:00:00:00:00:12"
        )

        async with inventory(app) as work:
            with counting(app) as statements:
                found = await work.units.find("12", 10)
            by_code = await work.units.find("wx-u-000", 10)
            by_mac = await work.units.find("00:12", 10)

        assert len(statements) == 1, statements
        assert [unit.id for unit in found] == [first.id]
        assert [str(unit.code) for unit in by_code] == ["WX-U-0001", "WX-U-0002"]
        assert [unit.id for unit in by_mac] == [first.id]

    async def test_a_unit_in_the_trash_or_of_another_bench_is_never_found(
        self, app: AsyncEngine
    ) -> None:
        # Requirements 2.1 and 2.2.
        kept, trashed = await units_coded(app, "WX-U-0001", "WX-U-0002")
        async with inventory(app) as work:
            gone = await work.units.get(trashed.id)
            assert gone is not None
            gone.retire()
            gone.move_to_trash(NOW)
            await work.commit()
        await units_coded(app, "WX-U-0003", workspace=OTHER)

        async with inventory(app) as work:
            found = await work.units.find("WX-U", 10)

        assert [unit.id for unit in found] == [kept.id]

    async def test_locations_are_found_by_name_or_code_starting_names_first(
        self, app: AsyncEngine
    ) -> None:
        await locations_named(
            app, ("WX-L-0001", "Lab"), ("WX-L-0002", "Drawer 3"), ("WX-L-0003", "Bin drawer")
        )
        await locations_named(app, ("WX-L-0001", "Drawer 1"), workspace=OTHER)

        async with inventory(app) as work:
            with counting(app) as statements:
                found = await work.locations.find("drawer", 10)
            by_code = await work.locations.find("l-0001", 10)
            limited = await work.locations.find("drawer", 1)

        assert len(statements) == 1, statements
        assert [str(location.name) for location in found] == ["Drawer 3", "Bin drawer"]
        assert [str(location.name) for location in by_code] == ["Lab"]
        assert [str(location.name) for location in limited] == ["Drawer 3"]


async def projects_named(app: AsyncEngine, *named: str, workspace: UUID = BENCH) -> list[UUID]:
    """Projects created as the app creates them, each with its revision A; their ids."""
    projects = projects_use_cases(create_session_factory(app))
    created = [
        await projects.create_project(
            ProjectsWorkspaceId(workspace), ProjectDetails(ProjectName(name))
        )
        for name in named
    ]
    return [view.project.id for view in created]


async def firmware_named(
    app: AsyncEngine, *named: tuple[str, str], workspace: UUID = BENCH
) -> list[UUID]:
    """Firmware created as the app creates them, each a (name, target) pair; their ids."""
    firmware = firmware_use_cases(create_session_factory(app))
    created = [
        await firmware.create_firmware(
            FirmwareWorkspaceId(workspace),
            FirmwareDetails(FirmwareName(name), BoardTarget(target), Framework.ARDUINO),
            None,
        )
        for name, target in named
    ]
    return [view.firmware.id for view in created]


class TestProjectsAndFirmware:
    async def test_projects_are_found_in_one_statement_starting_ones_first(
        self, app: AsyncEngine
    ) -> None:
        # Requirements 1.1, 1.3, 2.1, 2.2 and 6.1.
        await projects_named(app, "Old weather station", "weather vane", "Weather station")
        gone, _ = await projects_named(app, "Weather logger", "100% robot")
        await projects_use_cases(create_session_factory(app)).delete_project(
            ProjectsWorkspaceId(BENCH), ProjectId(gone)
        )
        await projects_named(app, "Weather balloon", workspace=OTHER)

        async with SqlProjectsUnitOfWork(
            create_session_factory(app), ProjectsWorkspaceId(BENCH), Uuid7Generator()
        ) as work:
            with counting(app) as statements:
                found = await work.projects.find("weather", 10)
            percent = await work.projects.find("100%", 10)
            limited = await work.projects.find("weather", 1)

        assert len(statements) == 1, statements
        assert [str(project.name) for project in found] == [
            "Weather station",
            "weather vane",
            "Old weather station",
        ]
        assert [str(project.name) for project in percent] == ["100% robot"]
        assert [str(project.name) for project in limited] == ["Weather station"]

    async def test_firmware_is_found_by_name_or_target_in_one_statement(
        self, app: AsyncEngine
    ) -> None:
        # Requirements 1.1, 1.3, 2.1, 2.2 and 6.1.
        await firmware_named(
            app,
            ("Old station", "esp32:esp32:esp32"),
            ("station blink", "esp32:esp32:esp32"),
            ("Logger", "rp2040:rp2040:pico"),
        )
        (gone,) = await firmware_named(app, ("Station spare", "esp32:esp32:esp32"))
        await firmware_use_cases(create_session_factory(app)).delete_firmware(
            FirmwareWorkspaceId(BENCH), FirmwareId(gone)
        )
        await firmware_named(app, ("Station theirs", "esp32:esp32:esp32"), workspace=OTHER)

        async with SqlFirmwareUnitOfWork(
            create_session_factory(app), FirmwareWorkspaceId(BENCH)
        ) as work:
            with counting(app) as statements:
                found = await work.firmwares.find("station", 10)
            by_target = await work.firmwares.find("PICO", 10)

        assert len(statements) == 1, statements
        assert [str(firmware.name) for firmware in found] == ["station blink", "Old station"]
        assert [str(firmware.name) for firmware in by_target] == ["Logger"]
