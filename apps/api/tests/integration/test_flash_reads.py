"""Firmware reading and locking inventory's units over Postgres, as `wiredex_app`, on
`SqlFlashUnitOfWork`'s one session (15-flash-log decision 8).

What only the real wiring can show: inventory's units are read in firmware's own transaction,
under the one workspace setting it applied, without which row-level security lets no unit
through. A unit's facts are its code as minted, whether it is retired and the revision holding
it while reserved or in use, any number of them in one plain read. `lock` takes the row 06's
retire takes, so a flash's lock waits for a retire of its unit to commit and then reads the unit
retired (requirement 1.11). Another bench's unit is one the workspace doesn't hold (1.10, 6.2).
A unit's log and a firmware's boards each cost a fixed number of statements, the setting
included, whatever the numbers of flashes, units and versions (decision 12, requirement 9.3).
"""

import asyncio
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID, uuid7

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from support.sql import counting
from wiredex.bootstrap.catalog import catalog_use_cases
from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.firmware import SqlFlashUnitOfWork, firmware_use_cases
from wiredex.bootstrap.inventory import inventory_use_cases
from wiredex.bootstrap.projects import projects_use_cases
from wiredex.bootstrap.settings import Environment, Settings
from wiredex.catalog.application.categories import NewCategory
from wiredex.catalog.application.parts import NewPart
from wiredex.catalog.domain.part import PartDetails
from wiredex.catalog.domain.values import CategoryName, PartName
from wiredex.catalog.domain.values import WorkspaceId as CatalogWorkspaceId
from wiredex.firmware.application.firmware import FlashUnitOfWorkFactory
from wiredex.firmware.application.flashes import GetUnitFirmware, ListBoards, LogFlash
from wiredex.firmware.application.ports import FlashUnitOfWork, NewFlash, NewSourceFile
from wiredex.firmware.domain.firmware import FirmwareDetails
from wiredex.firmware.domain.flash import UnitCode, UnitFacts
from wiredex.firmware.domain.values import (
    BoardTarget,
    Changelog,
    FirmwareId,
    FirmwareName,
    Framework,
    RevisionId,
    UnitId,
    VersionId,
    WorkspaceId,
)
from wiredex.inventory.application.builds import LotTake, RevisionStock
from wiredex.inventory.application.ports import NewLocation
from wiredex.inventory.application.units import NewUnit, UnitReceipt
from wiredex.inventory.domain.unit import Unit, UnitStatus
from wiredex.inventory.domain.values import LocationName, PartId
from wiredex.inventory.domain.values import RevisionId as InventoryRevisionId
from wiredex.inventory.domain.values import WorkspaceId as InventoryWorkspaceId
from wiredex.inventory.infrastructure.unit_of_work import (
    SqlInventoryRepositories,
    SqlInventoryUnitOfWork,
)
from wiredex.projects.domain.project import ProjectDetails
from wiredex.projects.domain.values import ProjectName
from wiredex.projects.domain.values import WorkspaceId as ProjectsWorkspaceId
from wiredex.shared_kernel.infrastructure.clock import SystemClock
from wiredex.shared_kernel.infrastructure.ids import Uuid7Generator

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

BENCH = WorkspaceId(uuid7())
OTHER = WorkspaceId(uuid7())
TABLES = (
    "flashes, source_files, firmware_versions, firmware_revisions, firmware, revisions,"
    " projects, units, stock_movements, stock_balances, stock_lots, short_code_counters,"
    " locations, pins, part_definitions, attribute_definitions, categories"
)
# Postgres's four row-locking clauses: `lock` sends one, `facts` none.
ROW_LOCK = re.compile(r"\bFOR (UPDATE|NO KEY UPDATE|SHARE|KEY SHARE)\b")


@pytest.fixture
async def admin(migrated_database_url: str) -> AsyncIterator[AsyncEngine]:
    """The schema owner, which the policies don't apply to: it sees every workspace."""
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
    """The API's role, with the API's engine: row security applies."""
    settings = Settings(environment=Environment.TEST, database_url=SecretStr(app_database_url))
    engine = create_engine(settings)
    yield engine
    await engine.dispose()


class Bench:
    """Catalog's, inventory's, projects' and firmware's use cases as the app wires them, for the
    units, builds and releases a flash names, and the flash use cases over `SqlFlashUnitOfWork`
    on the same engine."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions
        self.catalog = catalog_use_cases(sessions)
        self.inventory = inventory_use_cases(sessions)
        self.projects = projects_use_cases(sessions)
        self.firmware = firmware_use_cases(sessions)
        work: FlashUnitOfWorkFactory = self.flash_work
        self.log_flash = LogFlash(work, SystemClock(), Uuid7Generator())
        self.get_unit_firmware = GetUnitFirmware(work)
        self.list_boards = ListBoards(work)

    def flash_work(self, workspace_id: WorkspaceId = BENCH) -> FlashUnitOfWork:
        return SqlFlashUnitOfWork(self._sessions, workspace_id)

    async def revision(self) -> RevisionId:
        """Revision A of a project of its own, which a new project starts with."""
        details = ProjectDetails(ProjectName(f"Greenhouse controller {uuid7()}"))
        view = await self.projects.create_project(ProjectsWorkspaceId(BENCH), details)
        latest = view.revisions.latest
        assert latest is not None
        return RevisionId(latest.id)

    async def releases(self, count: int) -> tuple[FirmwareId, list[VersionId]]:
        """A firmware with `count` versions, from 0.1.0 up, each given a sketch and a changelog
        and released through 13's use cases."""
        details = FirmwareDetails(
            FirmwareName("Pico blink"), BoardTarget("RPI_PICO"), Framework.MICROPYTHON
        )
        firmware = (await self.firmware.create_firmware(BENCH, details)).firmware.id
        released: list[VersionId] = []
        for _ in range(count):
            draft = (await self.firmware.start_version(BENCH, firmware)).version
            sketch = NewSourceFile("main.py", "led.toggle()\n")
            await self.firmware.add_source_files(BENCH, draft.id, [sketch])
            changelog = Changelog("Blinks the LED once a second.")
            await self.firmware.update_version(BENCH, draft.id, draft.number, changelog)
            await self.firmware.release_version(BENCH, draft.id)
            released.append(draft.id)
        return firmware, released

    async def boards(self, count: int, workspace_id: WorkspaceId = BENCH) -> list[Unit]:
        """`count` ESP32 boards received into a drawer, coded from WX-U-0001 in that order."""
        catalog = CatalogWorkspaceId(workspace_id)
        created = await self.catalog.create_category(catalog, NewCategory(CategoryName("Boards")))
        category = created.category.id
        await self.catalog.set_category_tracking(catalog, category, True)
        part = await self.catalog.define_part(
            catalog, NewPart(category, PartDetails(PartName("ESP32-DevKitC")))
        )
        inventory = InventoryWorkspaceId(workspace_id)
        drawer = await self.inventory.create_location(inventory, NewLocation(LocationName("Box")))
        receipt = UnitReceipt(PartId(part.id), drawer.id, (NewUnit(),) * count)
        received = await self.inventory.receive_units(inventory, receipt)
        return list(received.units)

    async def hold(
        self, unit: Unit, *, build: bool = False, revision_id: RevisionId | None = None
    ) -> RevisionId:
        """The unit reserved for the revision, or one of its own, then built into it when asked,
        each in a transaction of its own, through inventory's `RevisionStock`: what 10's reserve
        and build do to a unit."""
        revision = InventoryRevisionId(uuid7() if revision_id is None else revision_id)
        async with self._stock() as stock:
            locked = await stock.available([unit.part_id], [unit.id])
            await stock.reserve(locked, revision, [LotTake(unit.lot_id, 1, (unit.id,))])
        if build:
            async with self._stock() as stock:
                await stock.consume(revision)
        return RevisionId(revision)

    @asynccontextmanager
    async def _stock(self) -> AsyncIterator[RevisionStock]:
        """`RevisionStock` on an inventory transaction of the bench, committed when the block
        ends, as `bootstrap/build.py` binds it on projects' transaction."""
        workspace = InventoryWorkspaceId(BENCH)
        async with SqlInventoryUnitOfWork(self._sessions, workspace) as work:
            repositories = SqlInventoryRepositories(work.session, workspace)
            yield RevisionStock(repositories, workspace, SystemClock(), Uuid7Generator())
            await work.commit()


@pytest.fixture
def bench(app: AsyncEngine) -> Bench:
    return Bench(create_session_factory(app))


def facts_of(unit: Unit, *, revision_id: RevisionId | None = None) -> UnitFacts:
    """The facts firmware should read of the unit, held by the revision when one is given."""
    retired = unit.status is UnitStatus.RETIRED
    return UnitFacts(UnitId(unit.id), UnitCode(str(unit.code)), retired, revision_id)


@asynccontextmanager
async def unit_held(admin: AsyncEngine, unit_id: UUID) -> AsyncIterator[None]:
    """The unit's row locked by an outside transaction until the block ends.

    Left to themselves, a retire and a flash started together mostly run one after the other,
    which would hide a missing lock. Holding the row lines them up behind it, in the order they
    asked for it.
    """
    async with admin.begin() as holder:
        await holder.execute(
            text("SELECT id FROM units WHERE id = :id FOR UPDATE"), {"id": unit_id}
        )
        yield


async def until_waiting(admin: AsyncEngine, count: int) -> None:
    """Returns once `count` transactions wait on a lock, or fails: a read that never waits for
    the unit's row isn't taking turns."""
    for _ in range(200):
        # A transaction each: pg_stat_activity is read once per transaction.
        async with admin.connect() as watcher:
            waiting = await watcher.scalar(
                text("SELECT count(*) FROM pg_stat_activity WHERE wait_event_type = 'Lock'")
            )
        if (waiting or 0) >= count:
            return
        await asyncio.sleep(0.05)
    pytest.fail(f"expected {count} transactions waiting for the unit's lock")


async def take_now(admin: AsyncEngine, unit_id: UUID) -> None:
    """The unit's row taken by an outside transaction, refused at once if another holds it."""
    async with admin.begin() as other:
        await other.execute(
            text("SELECT id FROM units WHERE id = :id FOR UPDATE NOWAIT"), {"id": unit_id}
        )


async def test_a_units_facts_are_read_and_locked_on_firmwares_session(
    bench: Bench, app: AsyncEngine, admin: AsyncEngine
) -> None:
    # Decision 8: firmware sees a unit as its code, whether it is retired, and the revision
    # holding it while it is reserved or in use. Each read is one statement on the session the
    # unit of work opened, under its setting, which row-level security needs to show any unit:
    # `facts` reads every listed unit at once, unlocked, and `lock` one, locked until the
    # transaction ends.
    stocked, reserved, built, retired = await bench.boards(4)
    reserved_for = await bench.hold(reserved)
    built_into = await bench.hold(built, build=True)
    retired = await bench.inventory.retire_unit(InventoryWorkspaceId(BENCH), retired.id)
    wanted = [UnitId(unit.id) for unit in (stocked, reserved, built, retired)]

    async with bench.flash_work() as work:
        with counting(app) as read:
            found = await work.units.facts([*wanted, UnitId(uuid7())])
        with counting(app) as locking:
            locked = await work.units.lock(UnitId(reserved.id))
        # Firmware's transaction holds the row: no other can take it until that one ends.
        with pytest.raises(DBAPIError, match="could not obtain lock"):
            await take_now(admin, reserved.id)
    await take_now(admin, reserved.id)

    assert retired.status is UnitStatus.RETIRED
    assert found == {
        UnitId(stocked.id): facts_of(stocked),
        UnitId(reserved.id): facts_of(reserved, revision_id=reserved_for),
        UnitId(built.id): facts_of(built, revision_id=built_into),
        UnitId(retired.id): facts_of(retired),
    }
    assert locked == found[UnitId(reserved.id)]
    assert len(read) == 1, read
    assert ROW_LOCK.search(read[0]) is None, read
    assert len(locking) == 1, locking
    assert ROW_LOCK.search(locking[0]) is not None, locking


async def test_a_flashs_lock_waits_for_a_retire_of_its_unit_and_reads_it_retired(
    bench: Bench, admin: AsyncEngine
) -> None:
    # Requirement 1.11: the retire queues for the unit's row first and the flash's lock behind
    # it. Once the retire commits, the lock reads the row fresh, so the flash finds its unit
    # retired, which `Flash.record` refuses, rather than recording a flash on it.
    [unit] = await bench.boards(1)

    async def lock() -> UnitFacts | None:
        async with bench.flash_work() as work:
            return await work.units.lock(UnitId(unit.id))

    async with unit_held(admin, unit.id):
        retiring = asyncio.create_task(
            bench.inventory.retire_unit(InventoryWorkspaceId(BENCH), unit.id)
        )
        await until_waiting(admin, 1)
        locking = asyncio.create_task(lock())
        await until_waiting(admin, 2)
    retired = await retiring
    locked = await locking

    assert retired.status is UnitStatus.RETIRED
    assert locked == facts_of(retired)


async def test_another_benchs_unit_is_one_the_workspace_doesnt_hold(bench: Bench) -> None:
    # Requirements 1.10 and 6.2: row-level security hides their unit from both reads, so the
    # directory answers it absent, as it does a deleted one, and a flash naming it is a 404.
    [mine] = await bench.boards(1)
    [theirs] = await bench.boards(1, OTHER)

    async with bench.flash_work() as work:
        assert await work.units.lock(UnitId(theirs.id)) is None
        found = await work.units.facts([UnitId(theirs.id), UnitId(mine.id)])

    assert found == {UnitId(mine.id): facts_of(mine)}
    # Their own bench holds it: the workspace refused it, not the id.
    async with bench.flash_work(OTHER) as work:
        assert await work.units.lock(UnitId(theirs.id)) == facts_of(theirs)


# --- What each read costs, whatever its sizes (decision 12) ----------------------------------


@pytest.mark.parametrize("count", [1, 40])
async def test_a_units_log_costs_five_statements_whatever_its_flashes(
    bench: Bench, app: AsyncEngine, count: int
) -> None:
    # `count` releases flashed onto a board a build holds, highest first, so the newest flash is
    # the lowest release and, past one, the highest is newer. Each flash recorded the build,
    # which row-level security would hide from a read outside the one setting.
    revision = await bench.revision()
    [board] = await bench.boards(1)
    await bench.hold(board, revision_id=revision)
    _, released = await bench.releases(count)
    for version_id in reversed(released):
        await bench.log_flash(BENCH, UnitId(board.id), NewFlash(version_id))

    with counting(app) as statements:
        view = await bench.get_unit_firmware(BENCH, UnitId(board.id))

    assert [flash.entry.flash.version_id for flash in view.flashes] == released
    assert {
        None if flash.revision is None else flash.revision.revision_id for flash in view.flashes
    } == {revision}
    newer = None if view.newer_release is None else view.newer_release.id
    assert newer == (None if count == 1 else released[-1])
    # The setting, the unit, its flashes with their versions and firmware, the revisions they
    # recorded, and the current firmware's versions.
    assert len(statements) == 5, statements


@pytest.mark.parametrize("count", [1, 40])
async def test_a_firmwares_boards_cost_six_statements_whatever_their_numbers(
    bench: Bench, app: AsyncEngine, count: int
) -> None:
    # `count` boards a build holds, each flashed with one of `count` releases: every board but
    # the one on the latest release has a newer one.
    revision = await bench.revision()
    boards = await bench.boards(count)
    for board in boards:
        await bench.hold(board, revision_id=revision)
    firmware, released = await bench.releases(count)
    for board, version_id in zip(boards, released, strict=True):
        await bench.log_flash(BENCH, UnitId(board.id), NewFlash(version_id))

    with counting(app) as statements:
        listed = await bench.list_boards(BENCH, firmware)

    # By code, which the boards were received in.
    assert [board.unit.unit_id for board in listed] == [UnitId(board.id) for board in boards]
    assert [board.current.entry.flash.version_id for board in listed] == released
    assert {board.revision for board in listed} == {listed[0].current.revision}
    assert listed[0].revision is not None
    assert listed[0].revision.revision_id == revision
    newer = [None if board.newer_release is None else board.newer_release.id for board in listed]
    assert newer == [released[-1]] * (count - 1) + [None]
    # The setting, the firmware, each unit's newest flash, the units, the revisions those
    # flashes recorded and those holding the units now, and the firmware's versions.
    assert len(statements) == 6, statements
