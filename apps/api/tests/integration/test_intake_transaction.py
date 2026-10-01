"""Quick-add and import over Postgres, as `wiredex_app`: one transaction across two modules.

`SqlIntakeUnitOfWork` binds catalog's repositories to the session inventory's unit of work
opened, so a part and its stock are written in one transaction, under one workspace setting,
and kept by one `commit()` (design decision 2). The use cases are the ones
`inventory_use_cases` wires for the routes. The in-memory fakes can't roll back, which is why
atomicity after a failed write is proved here and not as a property (Testing Strategy).
"""

import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid7

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from support.sql import committing, counting, row_counts
from wiredex.bootstrap.catalog import catalog_use_cases
from wiredex.bootstrap.database import create_engine, create_session_factory
from wiredex.bootstrap.inventory import inventory_use_cases
from wiredex.bootstrap.settings import Environment, Settings
from wiredex.catalog.api.router import CatalogUseCases
from wiredex.catalog.application.attributes import NewAttribute
from wiredex.catalog.application.categories import NewCategory
from wiredex.catalog.application.parts import NewPart
from wiredex.catalog.domain.part import PartDetails
from wiredex.catalog.domain.pinout import RawPin
from wiredex.catalog.domain.values import (
    AttributeKey,
    AttributeKind,
    AttributeLabel,
    CategoryId,
    CategoryName,
    Manufacturer,
    Mpn,
    PartDefinitionId,
    PartName,
)
from wiredex.catalog.domain.values import Unit as MeasureUnit
from wiredex.catalog.domain.values import WorkspaceId as CatalogWorkspaceId
from wiredex.inventory.api.router import InventoryUseCases
from wiredex.inventory.application.imports import ImportSheet, PreviewImport
from wiredex.inventory.application.intake import QuickAdd, QuickAddition, QuickStock
from wiredex.inventory.application.ports import NewLocation
from wiredex.inventory.domain.errors import IntakeRefusedError, PartNotFoundError
from wiredex.inventory.domain.intake import DefinesPart, NamesPart, PartDraft, ProblemCode
from wiredex.inventory.domain.location import Location
from wiredex.inventory.domain.lot import StockLot
from wiredex.inventory.domain.unit import Unit, UnitStatus
from wiredex.inventory.domain.values import (
    LocationName,
    PartId,
    ShortCode,
    StockLotId,
    UnitId,
    WorkspaceId,
)
from wiredex.inventory.infrastructure.unit_of_work import SqlInventoryUnitOfWork

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

NOW = datetime(2026, 9, 27, 10, tzinfo=UTC)
MINE = WorkspaceId(uuid7())
THEIRS = WorkspaceId(uuid7())
INTAKE_TABLES = (
    "units, stock_movements, stock_balances, stock_lots, short_code_counters, locations,"
    " pins, part_definitions, attribute_definitions, categories"
)
# A lot's one movement and its balance, for the part it holds.
STOCK_OF = (
    "SELECT m.kind::text, m.change, b.on_hand FROM stock_lots l"
    " JOIN stock_movements m ON m.lot_id = l.id JOIN stock_balances b ON b.lot_id = l.id"
    " WHERE l.part_id = :part"
)
WRITES = re.compile(r"\s*(INSERT|UPDATE|DELETE)\b", re.IGNORECASE)


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
        await connection.execute(text(f"TRUNCATE {INTAKE_TABLES} CASCADE"))


@pytest.fixture
async def app(app_database_url: str) -> AsyncIterator[AsyncEngine]:
    """The API's role, with the API's engine: row security applies, and Decimals stay exact."""
    settings = Settings(environment=Environment.TEST, database_url=SecretStr(app_database_url))
    engine = create_engine(settings)
    yield engine
    await engine.dispose()


@dataclass(frozen=True, slots=True)
class Wiring:
    """The intake use cases over `SqlIntakeUnitOfWork`, as the composition root wires them
    for the routes, and the catalog and inventory use cases that set a bench up."""

    quick_add: QuickAdd
    preview_import: PreviewImport
    import_sheet: ImportSheet
    catalog: CatalogUseCases
    inventory: InventoryUseCases


@pytest.fixture
def wiring(app: AsyncEngine) -> Wiring:
    session_factory = create_session_factory(app)
    inventory = inventory_use_cases(session_factory)
    return Wiring(
        inventory.quick_add,
        inventory.preview_import,
        inventory.import_sheet,
        catalog_use_cases(session_factory),
        inventory,
    )


@dataclass(frozen=True, slots=True)
class Bench:
    resistors: CategoryId
    boards: CategoryId
    drawer: Location


async def a_bench(wiring: Wiring, workspace: WorkspaceId) -> Bench:
    """*Passives → Resistors* with a required resistance in ohms, a unit-tracked *Boards*, and
    *Drawer 3*, the workspace's first location, so `WX-L-0001`."""
    catalog = CatalogWorkspaceId(workspace)
    passives = await wiring.catalog.create_category(catalog, NewCategory(CategoryName("Passives")))
    resistors = await wiring.catalog.create_category(
        catalog, NewCategory(CategoryName("Resistors"), passives.category.id)
    )
    resistance = NewAttribute(
        AttributeKey("resistance"),
        AttributeLabel("Resistance"),
        AttributeKind.NUMBER,
        MeasureUnit("Ω"),
        required=True,
    )
    await wiring.catalog.define_attribute(catalog, resistors.category.id, resistance)
    boards = await wiring.catalog.create_category(catalog, NewCategory(CategoryName("Boards")))
    await wiring.catalog.set_category_tracking(catalog, boards.category.id, True)
    drawer = await wiring.inventory.create_location(
        workspace, NewLocation(LocationName("Drawer 3"))
    )
    return Bench(resistors.category.id, boards.category.id, drawer)


async def rows(owner: AsyncEngine, sql: str, **parameters: object) -> list[tuple[object, ...]]:
    """A query as the schema owner, which sees what was committed in every workspace."""
    async with owner.connect() as connection:
        result = await connection.execute(text(sql), parameters)
        return [tuple(row) for row in result]


def a_resistor(bench: Bench, name: str, mpn: str, resistance: str) -> PartDraft:
    return PartDraft(
        category_id=bench.resistors,
        name=name,
        manufacturer="Yageo",
        mpn=mpn,
        attributes={"resistance": resistance},
    )


async def test_a_quick_adds_part_and_lot_land_in_one_commit(
    wiring: Wiring, app: AsyncEngine, admin: AsyncEngine
) -> None:
    bench = await a_bench(wiring, MINE)
    addition = QuickAddition(
        a_resistor(bench, "R 10k 0805", "RC0805FR-0710KL", "10k"), QuickStock(bench.drawer.id, 200)
    )

    with committing(app) as commits:
        added = await wiring.quick_add(MINE, addition)

    # One commit, and everything is there after it: the part, its lot, the RECEIVE, the
    # balance (requirements 1.2, 12.1).
    assert len(commits) == 1
    assert await rows(
        admin,
        "SELECT name, (attributes->>'resistance')::numeric FROM part_definitions WHERE id = :part",
        part=added.part.id,
    ) == [("R 10k 0805", Decimal(10000))]
    assert await rows(admin, STOCK_OF, part=added.part.id) == [("RECEIVE", 200, 200)]
    assert added.balance is not None
    assert int(added.balance.on_hand) == 200


async def test_a_quick_added_boards_units_land_in_the_same_commit(
    wiring: Wiring, app: AsyncEngine, admin: AsyncEngine
) -> None:
    bench = await a_bench(wiring, MINE)
    addition = QuickAddition(
        PartDraft(category_id=bench.boards, name="ESP32 board"), QuickStock(bench.drawer.id, 3)
    )

    with committing(app) as commits:
        added = await wiring.quick_add(MINE, addition)

    # Three units, blank labels, minted codes, one RECEIVE of 3 (requirement 1.3).
    assert len(commits) == 1
    assert [str(unit.code) for unit in added.units] == ["WX-U-0001", "WX-U-0002", "WX-U-0003"]
    assert await rows(
        admin,
        "SELECT code, serial, mac FROM units WHERE part_id = :part ORDER BY code",
        part=added.part.id,
    ) == [("WX-U-0001", None, None), ("WX-U-0002", None, None), ("WX-U-0003", None, None)]
    assert await rows(admin, STOCK_OF, part=added.part.id) == [("RECEIVE", 3, 3)]


async def test_a_duplicates_pins_land_in_the_commit_that_defines_it(
    wiring: Wiring, app: AsyncEngine
) -> None:
    bench = await a_bench(wiring, MINE)
    catalog = CatalogWorkspaceId(MINE)
    source = await wiring.catalog.define_part(
        catalog,
        NewPart(bench.boards, PartDetails(PartName("BME280 breakout"), Manufacturer("Bosch"))),
    )
    pinout = await wiring.catalog.replace_pinout(
        catalog,
        source.id,
        [
            RawPin(number="1", label="GND", type="ground"),
            RawPin(number="2", label="VDD", type="power", voltage="3V3"),
            RawPin(number="3", label="SDI", type="io", functions=("SDA", "MOSI")),
        ],
    )
    duplicate = QuickAddition(
        PartDraft(category_id=bench.boards, name="BME280 breakout, spare", manufacturer="Bosch"),
        QuickStock(bench.drawer.id, 1),
        pinout_from=PartId(source.id),
    )

    with committing(app) as commits:
        added = await wiring.quick_add(MINE, duplicate)

    # The pins were flushed after the part they point at, in the same transaction (3.2).
    assert len(commits) == 1
    copied = await wiring.catalog.get_pinout(catalog, PartDefinitionId(added.part.id))
    assert list(copied) == list(pinout)
    # The source is only read (requirement 3.3).
    assert await wiring.catalog.get_pinout(catalog, source.id) == pinout


async def a_unit_code_the_counter_never_minted(engine: AsyncEngine, location: Location) -> None:
    """A unit already holding `WX-U-0001` while the workspace's unit counter never moved.

    The next unit minted then collides on `uq_units_workspace_id_code`: a write that fails only
    after an import has defined its parts and received its first lot.
    """
    lot = StockLot(StockLotId(uuid7()), MINE, PartId(uuid7()), location.id, NOW)
    unit = Unit(
        UnitId(uuid7()),
        MINE,
        lot.part_id,
        lot.id,
        ShortCode("WX-U-0001"),
        None,
        None,
        UnitStatus.IN_STOCK,
        NOW,
    )
    async with SqlInventoryUnitOfWork(create_session_factory(engine), MINE) as work:
        await work.lots.add(lot)
        await work.units.add(unit)
        await work.commit()


async def test_an_import_failing_after_its_parts_are_defined_keeps_none_of_it(
    wiring: Wiring, app: AsyncEngine, admin: AsyncEngine
) -> None:
    bench = await a_bench(wiring, MINE)
    await a_unit_code_the_counter_never_minted(app, bench.drawer)
    # Row 2 defines a resistor and receives its lot; row 3 defines a board, whose unit fails.
    sheet = (
        "category,name,mpn,resistance,location,quantity,serial\n"
        "Passives / Resistors,R 10k 0805,RC0805FR-0710KL,10k,WX-L-0001,100,\n"
        "Boards,ESP32 board,,,WX-L-0001,,SN-0001\n"
    )
    plan = await wiring.preview_import(MINE, sheet)
    assert plan.problems == ()
    before = await row_counts(admin)

    with pytest.raises(IntegrityError, match="uq_units_workspace_id_code"):
        await wiring.import_sheet(MINE, sheet, plan.digest)

    # No part, lot, movement, balance or unit of it, in any table (requirement 8.4).
    assert await row_counts(admin) == before
    assert await rows(admin, "SELECT name FROM part_definitions") == []


async def test_a_preview_leaves_every_table_as_it_was(
    wiring: Wiring, app: AsyncEngine, admin: AsyncEngine
) -> None:
    bench = await a_bench(wiring, MINE)
    stocked = await wiring.quick_add(
        MINE,
        QuickAddition(
            a_resistor(bench, "R 4k7 0805", "RC0805FR-074K7L", "4k7"),
            QuickStock(bench.drawer.id, 50),
        ),
    )
    # A new part with a lot, the stored part with more, and a board with its MAC: a plan that
    # would write to every intake table if it were imported.
    sheet = (
        "categoria;nome;fabricante;mpn;resistance;local;quantidade;mac\n"
        "Passives / Resistors;R 10k 0805;Yageo;RC0805FR-0710KL;10k;Drawer 3;100;\n"
        ";;Yageo;rc0805fr-074k7l;;wx-l-0001;25;\n"
        "Boards;ESP32 board;;;;WX-L-0001;;AA-BB-CC-00-11-22\n"
    )
    before = await row_counts(admin)

    with counting(app) as statements:
        plan = await wiring.preview_import(MINE, sheet)

    assert plan.problems == ()
    assert isinstance(plan.rows[0].part, DefinesPart)
    assert plan.rows[1].part == NamesPart(stocked.part)
    assert isinstance(plan.rows[2].part, DefinesPart)
    # Nothing written, not even a short code minted (requirement 7.1).
    assert await row_counts(admin) == before
    assert [statement for statement in statements if WRITES.match(statement)] == []


async def test_another_workspaces_category_part_and_location_are_unknown_to_a_sheet(
    wiring: Wiring,
) -> None:
    await a_bench(wiring, MINE)
    theirs = CatalogWorkspaceId(THEIRS)
    secret = await wiring.catalog.create_category(theirs, NewCategory(CategoryName("Secret")))
    sensors = await wiring.catalog.create_category(
        theirs, NewCategory(CategoryName("Sensors"), secret.category.id)
    )
    details = PartDetails(PartName("BME280"), Manufacturer("Bosch"), Mpn("BME280"))
    await wiring.catalog.define_part(theirs, NewPart(sensors.category.id, details))
    await wiring.inventory.create_location(THEIRS, NewLocation(LocationName("Vault")))
    await wiring.inventory.create_location(THEIRS, NewLocation(LocationName("Safe")))
    header = "category,name,manufacturer,mpn,location,quantity\n"
    sheet = (
        f"{header}"
        "Secret / Sensors,Sensor,,,Drawer 3,1\n"
        ",,Bosch,BME280,Drawer 3,5\n"
        "Boards,Pico,,,WX-L-0002,1\n"
        "Boards,Pico 2,,,Safe,1\n"
    )

    plan = await wiring.preview_import(MINE, sheet)

    # Their category path, their part number and their location code and path are simply not
    # there (requirement 10.2): their part number defines a part of mine, which then needs a
    # category and a name of its own.
    assert [[(p.column, p.code) for p in row.problems] for row in plan.rows] == [
        [("category", ProblemCode.UNKNOWN_CATEGORY)],
        [("category", ProblemCode.MISSING), ("name", ProblemCode.MISSING)],
        [("location", ProblemCode.UNKNOWN_LOCATION)],
        [("location", ProblemCode.UNKNOWN_LOCATION)],
    ]
    assert isinstance(plan.rows[1].part, DefinesPart)
    # In their own bench the same cells name their part and their bin.
    own = await wiring.preview_import(THEIRS, f"{header},,Bosch,BME280,WX-L-0002,5\n")
    assert own.problems == ()
    assert isinstance(own.rows[0].part, NamesPart)


async def test_a_quick_add_cant_reach_another_workspaces_category_location_or_part(
    wiring: Wiring, admin: AsyncEngine
) -> None:
    bench = await a_bench(wiring, MINE)
    their_bench = await a_bench(wiring, THEIRS)
    their_part = await wiring.catalog.define_part(
        CatalogWorkspaceId(THEIRS), NewPart(their_bench.boards, PartDetails(PartName("Pico")))
    )
    before = await row_counts(admin)

    with pytest.raises(IntakeRefusedError) as refused:
        await wiring.quick_add(
            MINE,
            QuickAddition(
                PartDraft(category_id=their_bench.boards, name="Pico"),
                QuickStock(their_bench.drawer.id, 1),
            ),
        )
    with pytest.raises(PartNotFoundError):
        await wiring.quick_add(
            MINE,
            QuickAddition(
                PartDraft(category_id=bench.boards, name="Pico, spare"),
                pinout_from=PartId(their_part.id),
            ),
        )

    assert [(p.column, p.code) for p in refused.value.problems] == [
        ("category", ProblemCode.UNKNOWN_CATEGORY),
        ("location", ProblemCode.UNKNOWN_LOCATION),
    ]
    assert await row_counts(admin) == before


async def test_a_quick_add_naming_a_part_in_the_trash_is_refused_on_its_mpn(
    wiring: Wiring, admin: AsyncEngine
) -> None:
    # 16's requirement 3.3: the part keeps its MPN in the trash, and catalog's problem reaches
    # inventory as the code of the same name.
    bench = await a_bench(wiring, MINE)
    catalog = CatalogWorkspaceId(MINE)
    stored = await wiring.catalog.define_part(
        catalog,
        NewPart(
            bench.resistors,
            PartDetails(PartName("R 4k7 0805"), Manufacturer("Yageo"), Mpn("RC0805FR-074K7L")),
            {"resistance": "4k7"},
        ),
    )
    await wiring.catalog.delete_part(catalog, stored.id)
    before = await row_counts(admin)

    with pytest.raises(IntakeRefusedError) as refused:
        await wiring.quick_add(
            MINE,
            QuickAddition(
                a_resistor(bench, "R 4k7, again", "rc0805fr-074k7l", "4k7"),
                QuickStock(bench.drawer.id, 10),
            ),
        )

    assert [(p.column, p.code) for p in refused.value.problems] == [
        ("mpn", ProblemCode.PART_IN_TRASH)
    ]
    assert await row_counts(admin) == before
