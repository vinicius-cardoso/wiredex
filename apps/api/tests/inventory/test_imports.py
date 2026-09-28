"""Preview and import over the in-memory intake: every row of a sheet planned against the
bench, then the plan carried out in one unit of work.

The catalog's half is `FakePartCatalog`, as in the quick-add tests, so these pin what
inventory does with its answers: which part a row stocks, the stock it plans, its labels
checked against earlier rows and stored units, and that nothing is written unless a clean
plan is imported with the digest its preview answered. Properties 4, 5 and 7 close the file,
over generated sheets and benches.
"""

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from uuid import UUID, uuid7

import anyio
import pytest
from hypothesis import given
from hypothesis import strategies as st

from support.inventory import BENCH, World
from wiredex.inventory.application.imports import ImportResult
from wiredex.inventory.application.intake import QuickAdded, QuickAddition, QuickStock
from wiredex.inventory.application.ports import Receipt
from wiredex.inventory.application.units import NewUnit, UnitReceipt
from wiredex.inventory.domain.errors import (
    ImportChangedError,
    IntakeRefusedError,
    SheetUnreadableError,
)
from wiredex.inventory.domain.intake import (
    CellProblem,
    DefinesPart,
    ImportPlan,
    ImportSummary,
    NamesPart,
    PartDraft,
    PlannedRow,
    ProblemCode,
    ReceivesLot,
    ReceivesUnits,
    SameAsRow,
    StockOutcome,
    UnitLabels,
)
from wiredex.inventory.domain.sheet import Column, Sheet, SheetRow, write_sheet
from wiredex.inventory.domain.unit import Unit
from wiredex.inventory.domain.values import (
    LocationId,
    Mac,
    MovementKind,
    PartId,
    Quantity,
    Serial,
    UnitId,
)

pytestmark = pytest.mark.anyio

HEADER = "category,name,manufacturer,mpn,location,quantity,serial,mac"


def sheet_of(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def where(problems: Sequence[CellProblem]) -> list[tuple[int | None, str | None, ProblemCode]]:
    return [(problem.row, problem.column, problem.code) for problem in problems]


async def on_hand(world: World, part_id: PartId, location_id: LocationId) -> int:
    lot = await world.inventory.lots.for_part_at(part_id, location_id)
    assert lot is not None
    balance = await world.inventory.balances.get(lot.id)
    assert balance is not None
    return int(balance.on_hand)


def stores(world: World) -> tuple[object, ...]:
    """Everything an intake could write, and the commits, as they stand."""
    inventory = world.inventory
    return (
        dict(inventory.catalog.parts),
        list(inventory.catalog.defined),
        dict(inventory.locations.saved),
        dict(inventory.lots.saved),
        list(inventory.ledger.saved),
        dict(inventory.balances.saved),
        dict(inventory.units.saved),
        inventory.commits,
    )


# --- The part a row stocks -----------------------------------------------------------------------


class TestParts:
    async def test_a_row_naming_a_stored_part_stocks_it_and_ignores_its_other_cells(
        self,
    ) -> None:
        # Requirement 5.1: matched folded, as the unique index folds; `Nowhere` is ignored.
        world = World()
        held = world.inventory.catalog.hold_part(
            "10k 0805", world.resistors, manufacturer="Yageo", mpn="RC0805FR-0710KL"
        )
        text = sheet_of(HEADER, "Nowhere,,yageo, rc0805fr-0710kl ,WX-L-0002,200,,")

        plan = await world.preview_import(BENCH, text)
        await world.import_sheet(BENCH, text, plan.digest)

        stock = ReceivesLot(world.drawer, Quantity(200))
        assert plan.rows == (PlannedRow(2, NamesPart(held), stock, ()),)
        assert world.inventory.catalog.defined == []
        assert await on_hand(world, held.id, world.drawer.id) == 200

    async def test_a_later_row_giving_the_same_part_number_stocks_the_part_the_first_defines(
        self,
    ) -> None:
        # Requirement 5.2: the later row's other part cells are ignored, as for a stored part.
        world = World()
        text = sheet_of(
            HEADER,
            "Passives / Resistors,10k 0805,,R-1,WX-L-0002,5,,",
            ",,,r-1,WX-L-0002,7,,",
        )

        plan = await world.preview_import(BENCH, text)
        result = await world.import_sheet(BENCH, text, plan.digest)

        assert (plan.rows[1].part, plan.rows[1].problems) == (SameAsRow(2, False), ())
        [defined] = result.parts
        assert defined.row == 2
        assert await on_hand(world, defined.part.id, world.drawer.id) == 12
        assert [(m.kind, m.change) for m in world.inventory.ledger.saved] == [
            (MovementKind.RECEIVE, 5),
            (MovementKind.RECEIVE, 7),
        ]

    async def test_two_rows_without_a_part_number_plan_two_parts(self) -> None:
        # Requirement 5.8: nothing to match on, so each row is a part of its own.
        world = World()
        row = "Passives / Resistors,10k 0805,,,WX-L-0002,5,,"
        text = sheet_of(HEADER, row, row)

        plan = await world.preview_import(BENCH, text)
        result = await world.import_sheet(BENCH, text, plan.digest)

        assert [type(planned.part) for planned in plan.rows] == [DefinesPart, DefinesPart]
        assert [imported.row for imported in result.parts] == [2, 3]
        assert len({imported.part.id for imported in result.parts}) == 2
        assert len(world.inventory.catalog.defined) == 2

    async def test_a_blank_attribute_cell_is_an_attribute_not_given(self) -> None:
        # Requirement 5.6: the required address left blank is missing, not an empty value.
        world = World()
        world.inventory.catalog.add_category("Sensors", required=["i2c_address"])
        text = sheet_of("category,name,i2c_address,tolerance", "Sensors,BME280,,1%")

        plan = await world.preview_import(BENCH, text)

        [planned] = plan.rows
        assert isinstance(planned.part, DefinesPart)
        assert planned.part.draft.attributes == {"tolerance": "1%"}
        assert where(planned.problems) == [(2, "i2c_address", ProblemCode.MISSING)]


# --- Labels against earlier rows and the stored units --------------------------------------------


class TestLabels:
    async def test_a_stored_serial_is_refused_for_its_part_and_allowed_for_another(
        self,
    ) -> None:
        # Requirement 6.9: a serial is unique per part, compared folded.
        world = World()
        catalog = world.inventory.catalog
        held = catalog.hold_part("ESP32 DevKit", world.boards, manufacturer="Espressif", mpn="DK")
        catalog.hold_part("Pico W", world.boards, manufacturer="Raspberry Pi", mpn="SC0918")
        world.hold_unit(held.id, world.hold_lot(held.id, world.drawer, 1), serial=Serial("SN-1"))
        text = sheet_of(
            HEADER,
            ",,Espressif,DK,WX-L-0002,,sn-1,",
            ",,Raspberry Pi,SC0918,WX-L-0002,,SN-1,",
            "Boards,Spare board,,,WX-L-0002,,SN-1,",
        )

        plan = await world.preview_import(BENCH, text)

        assert where(plan.problems) == [(2, "serial", ProblemCode.SERIAL_TAKEN)]
        assert (
            plan.problems[0].message == "another unit of ESP32 DevKit already has the serial sn-1"
        )
        assert plan.rows[0].stock is None
        labelled = (UnitLabels(Serial("SN-1"), None),)
        assert [row.stock for row in plan.rows[1:]] == [
            ReceivesUnits(world.drawer, labelled),
            ReceivesUnits(world.drawer, labelled),
        ]

    async def test_a_stored_mac_is_refused_whichever_part_it_comes_with(self) -> None:
        # Once per label: the second row is told about the first, not the stored unit again.
        world = World()
        held = world.inventory.catalog.hold_part("ESP32 DevKit", world.boards, mpn="DK")
        lot = world.hold_lot(held.id, world.drawer, 1)
        world.hold_unit(held.id, lot, mac=Mac("aa:bb:cc:dd:ee:ff"))
        text = sheet_of(
            HEADER,
            "Boards,Spare board,,,WX-L-0002,,,AA-BB-CC-DD-EE-FF",
            "Boards,Other board,,,WX-L-0002,1,,aabb.ccdd.eeff",
        )

        plan = await world.preview_import(BENCH, text)

        assert where(plan.problems) == [
            (2, "mac", ProblemCode.MAC_TAKEN),
            (3, "mac", ProblemCode.MAC_TAKEN),
        ]
        assert [problem.message for problem in plan.problems] == [
            "another unit in this workspace already has the MAC aa:bb:cc:dd:ee:ff",
            "row 2 already has the MAC aa:bb:cc:dd:ee:ff",
        ]
        assert [row.stock for row in plan.rows] == [None, None]


# --- The plan as a whole -------------------------------------------------------------------------


class TestPlan:
    async def test_the_summary_counts_what_the_sheet_will_do(self) -> None:
        # Requirements 7.2, 7.3 and 7.5: a row with a problem is still planned and counted.
        world = World()
        world.inventory.catalog.hold_part(
            "10k 0805", world.resistors, manufacturer="Yageo", mpn="RC0805"
        )
        text = sheet_of(
            HEADER,
            "Passives / Resistors,10k 0805,,R-1,WX-L-0002,200,,",
            ",,,R-1,Lab / Drawer 3,50,,",
            "Nowhere,,Yageo,RC0805,WX-L-0001,5,,",
            "Boards,ESP32-C3,,,WX-L-0002,3,,",
            "Boards,Board,,,drawer 3,,SN-7,aa-bb-cc-dd-ee-07",
            ",No category,,,,,,",
        )

        plan = await world.preview_import(BENCH, text)

        assert plan.summary == ImportSummary(
            rows=6,
            new_parts=4,
            existing_parts=1,
            receipts=3,
            pieces=255,
            units=4,
            rows_with_problems=1,
        )
        assert where(plan.problems) == [(7, "category", ProblemCode.MISSING)]
        assert [type(row.part) for row in plan.rows] == [
            DefinesPart,
            SameAsRow,
            NamesPart,
            DefinesPart,
            DefinesPart,
            DefinesPart,
        ]

    async def test_a_cell_past_the_last_column_is_the_rows_first_problem(self) -> None:
        # Requirement 4.7: `10k, 1%` unquoted shifts every cell after it.
        world = World()
        text = sheet_of(
            "category,name,location,quantity", "Passives / Resistors,10k, 1%,WX-L-0002,5"
        )

        plan = await world.preview_import(BENCH, text)

        assert where(plan.problems)[0] == (2, None, ProblemCode.EXTRA_CELLS)
        assert "needs quotes" in plan.problems[0].message

    @pytest.mark.parametrize("rows", [1, 60])
    async def test_the_location_tree_is_read_once_whatever_the_rows(self, rows: int) -> None:
        # Requirement 12.2, for a preview and again for an import.
        world = World()
        lines = [f"Passives / Resistors,R{n},WX-L-0002,{n}" for n in range(1, rows + 1)]
        text = sheet_of("category,name,location,quantity", *lines)

        plan = await world.preview_import(BENCH, text)
        assert world.inventory.locations.tree_reads == 1

        await world.import_sheet(BENCH, text, plan.digest)
        assert world.inventory.locations.tree_reads == 2

    @pytest.mark.parametrize("text", ["", "name,nome\n"], ids=["empty", "a column twice"])
    async def test_a_sheet_that_cant_be_read_is_refused_before_a_unit_of_work_opens(
        self, text: str
    ) -> None:
        world = World()

        with pytest.raises(SheetUnreadableError):
            await world.preview_import(BENCH, text)
        with pytest.raises(SheetUnreadableError):
            await world.import_sheet(BENCH, text, "0" * 64)

        assert world.inventory.opened_for == []


# --- The import ----------------------------------------------------------------------------------


class TestImport:
    async def test_an_import_defines_and_receives_in_row_order_and_commits_once(self) -> None:
        # Requirements 8.1, 8.5 and 8.6: one RECEIVE per row, the parts and units answered.
        world = World()
        text = sheet_of(
            HEADER,
            "Passives / Resistors,10k 0805,,R-1,WX-L-0002,200,,",
            "Boards,ESP32-C3,,B-1,WX-L-0002,2,,",
            ",,,R-1,WX-L-0001,5,,",
            ",,,B-1,WX-L-0002,,SN-1,",
        )

        plan = await world.preview_import(BENCH, text)
        result = await world.import_sheet(BENCH, text, plan.digest)

        resistor, board = (imported.part for imported in result.parts)
        assert [(imported.row, imported.part.name) for imported in result.parts] == [
            (2, "10k 0805"),
            (3, "ESP32-C3"),
        ]
        assert [(str(unit.code), unit.serial) for unit in result.units] == [
            ("WX-U-0001", None),
            ("WX-U-0002", None),
            ("WX-U-0003", Serial("SN-1")),
        ]
        assert {unit.part_id for unit in result.units} == {board.id}
        assert await on_hand(world, resistor.id, world.drawer.id) == 200
        assert await on_hand(world, resistor.id, world.lab.id) == 5
        assert await on_hand(world, board.id, world.drawer.id) == 3
        changes = [(m.kind, m.change) for m in world.inventory.ledger.saved]
        assert changes == [(MovementKind.RECEIVE, change) for change in (200, 2, 5, 1)]
        assert result.summary == plan.summary
        assert world.inventory.opened_for == [BENCH, BENCH]
        assert world.inventory.commits == 1

    async def test_a_plan_with_problems_is_refused_with_them_all(self) -> None:
        # Requirement 8.2, even with the preview's own digest.
        world = World()
        text = sheet_of(HEADER, ",10k 0805,,,Nowhere,5,,", "Passives / Resistors,4k7,,,,,,")
        plan = await world.preview_import(BENCH, text)

        with pytest.raises(IntakeRefusedError) as refused:
            await world.import_sheet(BENCH, text, plan.digest)

        assert refused.value.problems == plan.problems
        assert where(refused.value.problems) == [
            (2, "category", ProblemCode.MISSING),
            (2, "location", ProblemCode.UNKNOWN_LOCATION),
        ]
        assert str(refused.value) == "the sheet can't be imported as it is"
        assert world.inventory.catalog.defined == []
        assert world.inventory.commits == 0

    async def test_a_part_number_taken_since_the_preview_is_refused_as_changed(self) -> None:
        # Requirement 8.3: the row would now stock that part rather than define its own.
        world = World()
        text = sheet_of(HEADER, "Passives / Resistors,10k 0805,,R-1,WX-L-0002,5,,")
        plan = await world.preview_import(BENCH, text)
        world.inventory.catalog.hold_part("Meanwhile", world.resistors, mpn="R-1")

        with pytest.raises(ImportChangedError) as refused:
            await world.import_sheet(BENCH, text, plan.digest)

        assert str(refused.value) == (
            "the sheet's outcome changed since its preview; preview it again"
        )
        assert world.inventory.catalog.defined == []
        assert world.inventory.lots.saved == {}
        assert world.inventory.commits == 0


# --- The benches and sheets the properties draw --------------------------------------------------

# Every column a generated sheet may fill; a cell a row doesn't give is written blank.
COLUMNS = (*Column, "tolerance", "i2c_address")

STORED_SERIAL = "SN-STORED"
STORED_MAC = "02:00:00:00:00:ff"


@dataclass(frozen=True)
class Start:
    """What the bench holds before the sheet: its stored parts and their stock, received
    through the ledger, so a lot's on_hand always agrees with its movements."""

    resistor: bool  # Yageo RC0805, in Passives / Resistors
    resistor_stock: int  # in Drawer 3; 0 for none
    board: bool  # Espressif DEVKIT, in Boards
    board_unit: bool  # one unit of it, holding STORED_SERIAL and STORED_MAC


_STARTS = st.builds(Start, st.booleans(), st.integers(0, 3), st.booleans(), st.booleans())
_EMPTY = Start(resistor=False, resistor_stock=0, board=False, board_unit=False)


async def bench(start: Start) -> World:
    """The world's bench and catalog, a Sensors category that requires an address, a Shelf
    and two Bins (one under Drawer 3, one on the Shelf), and what `start` stores."""
    world = World()
    world.inventory.catalog.add_category("Sensors", required=["i2c_address"])
    shelf = world.add_location("Shelf")  # WX-L-0003
    world.add_location("Bin", world.drawer)  # WX-L-0004
    world.add_location("Bin", shelf)  # WX-L-0005
    if start.resistor:
        await _store_resistor(world, start.resistor_stock)
    if start.board:
        await _store_board(world, with_unit=start.board_unit)
    return world


async def _store_resistor(world: World, stock: int) -> None:
    resistor = world.inventory.catalog.hold_part(
        "10k 0805", world.resistors, manufacturer="Yageo", mpn="RC0805"
    )
    if stock:
        receipt = Receipt(resistor.id, world.drawer.id, Quantity(stock))
        await world.receive_stock.perform(BENCH, world.inventory, receipt)


async def _store_board(world: World, *, with_unit: bool) -> None:
    board = world.inventory.catalog.hold_part(
        "ESP32 DevKit", world.boards, manufacturer="Espressif", mpn="DEVKIT"
    )
    if with_unit:
        unit = NewUnit(Serial(STORED_SERIAL), Mac(STORED_MAC))
        receipt = UnitReceipt(board.id, world.drawer.id, (unit,))
        await world.receive_units.perform(BENCH, world.inventory, receipt)


def text_of(rows: Sequence[Mapping[str, str]]) -> str:
    """The rows as a sheet's text, numbered from 2 under a header of every column."""
    written = tuple(SheetRow(number, cells, False) for number, cells in enumerate(rows, 2))
    return write_sheet(Sheet(COLUMNS, written))


# Rows that read whatever the bench holds. A row that may name a stored part gives the
# stored part's own category and a name too, so that without it the row defines a part of the
# same kind, and the stock fits either way. Part numbers new to the bench are kept apart
# between resistors and boards, and labels are made from the row's index, so no two rows of a
# sheet, and no row and the stored unit, share one.
_RESISTOR_NAMINGS = (("", ""), ("Yageo", "RC0805"), ("", "R-1"), ("", "R-2"))
_BOARD_NAMINGS = (("", ""), ("Espressif", "DEVKIT"), ("", "B-1"))
_PLACES = ("WX-L-0002", "wx-l-0001", "Lab / Drawer 3", "shelf", "Drawer 3 / Bin")


@st.composite
def clean_cells(draw: st.DrawFn, index: int) -> dict[str, str]:
    board = draw(st.booleans())
    manufacturer, mpn = draw(st.sampled_from(_BOARD_NAMINGS if board else _RESISTOR_NAMINGS))
    cells = {
        Column.CATEGORY: "Boards" if board else "Passives / Resistors",
        Column.NAME: draw(st.sampled_from(["10k 0805", "ESP32 DevKit", "Spare"])),
        Column.MANUFACTURER: manufacturer,
        Column.MPN: mpn,
        "tolerance": draw(st.sampled_from(["", "1%"])),
    }
    return cells | draw(clean_stock(index, board=board))


@st.composite
def clean_stock(draw: st.DrawFn, index: int, *, board: bool) -> dict[str, str]:
    """No stock, a count (of pieces or of units), or one board labelled by the row."""
    kind = draw(st.sampled_from(["none", "count", "labelled"] if board else ["none", "count"]))
    if kind == "none":
        return {}
    place: dict[str, str] = {Column.LOCATION: draw(st.sampled_from(_PLACES))}
    if kind == "count":
        return place | {Column.QUANTITY: str(draw(st.integers(1, 3 if board else 500)))}
    serial, mac = f"SN-{index}", f"02:00:00:00:{index:02x}:01"
    labels = draw(st.sampled_from([(serial, ""), ("", mac), (serial, mac)]))
    quantity = draw(st.sampled_from(["", "1"]))
    return place | {Column.QUANTITY: quantity, Column.SERIAL: labels[0], Column.MAC: labels[1]}


# Rows from pools of cells that collide with each other and with the bench: unknown or
# missing categories and names, stored and repeated part numbers and labels, locations that
# are ambiguous or don't exist, quantities that don't read.
_ANY_CELLS: Mapping[str, tuple[str, ...]] = {
    Column.CATEGORY: ("", "Passives / Resistors", "boards", "Sensors", "Nowhere"),
    Column.NAME: ("", "10k 0805", "BME280"),
    Column.MANUFACTURER: ("", "Yageo", "Espressif"),
    Column.MPN: ("", "RC0805", "DEVKIT", "NEW-1"),
    Column.LOCATION: ("", "WX-L-0002", "wx-l-0001", "Lab / Drawer 3", "Bin", "Nowhere"),
    Column.QUANTITY: ("", "1", "3", "0", "many", "101"),
    Column.SERIAL: ("", "SN-1", STORED_SERIAL),
    Column.MAC: ("", "02:00:00:00:00:01", "02-00-00-00-00-FF", "zz"),
    "i2c_address": ("", "0x76"),
}


@st.composite
def any_cells(draw: st.DrawFn) -> dict[str, str]:
    return {column: draw(st.sampled_from(cells)) for column, cells in _ANY_CELLS.items()}


@st.composite
def clean_sheets(draw: st.DrawFn) -> str:
    count = draw(st.integers(1, 4))
    return text_of([draw(clean_cells(index)) for index in range(count)])


@st.composite
def any_sheets(draw: st.DrawFn) -> str:
    count = draw(st.integers(0, 4))
    return text_of([draw(clean_cells(index) | any_cells()) for index in range(count)])


def other_digests(digest: str) -> st.SearchStrategy[str]:
    return st.text("0123456789abcdef", min_size=64, max_size=64).filter(lambda d: d != digest)


# --- Property 4 ----------------------------------------------------------------------------------


def changed_since(world: World, plan: ImportPlan, data: st.DataObject) -> str:
    """A digest other than the one the plan has now: another one sent, or the plan's own
    after a part holding one of the sheet's new part numbers appeared since the preview. The
    part appears in the row's own category, so the row still reads and only its outcome
    changes."""
    numbered = [
        row.part
        for row in plan.rows
        if isinstance(row.part, DefinesPart) and row.part.identity is not None
    ]
    if not numbered or not data.draw(st.booleans(), label="a part appears meanwhile"):
        return data.draw(other_digests(plan.digest), label="another digest")
    new = data.draw(st.sampled_from(numbered), label="the new part it takes the number of")
    assert new.category_id is not None
    category = world.inventory.catalog.categories[new.category_id]
    draft = new.draft
    world.inventory.catalog.hold_part(
        "Meanwhile", category, manufacturer=draft.manufacturer, mpn=draft.mpn
    )
    return plan.digest


@given(start=_STARTS, text=clean_sheets() | any_sheets(), data=st.data())
def test_nothing_is_written_unless_a_clean_plan_is_confirmed(
    start: Start, text: str, data: st.DataObject
) -> None:
    """Property 4: nothing is written unless a clean plan is confirmed.

    Previewing any sheet on any bench leaves every store as it was and commits nothing.
    Importing a sheet whose plan has a problem, with any digest, is refused with those
    problems; importing a clean one with a digest other than its plan's, including after a
    part holding one of its new part numbers appeared since the preview, is refused as
    changed. Either way every store is left as it was and nothing is committed.

    **Validates: Requirements 7.1, 8.2, 8.3**
    """

    async def scenario() -> None:
        world = await bench(start)
        before = stores(world)
        plan = await world.preview_import(BENCH, text)
        assert stores(world) == before
        if plan.problems:
            digest = data.draw(st.just(plan.digest) | other_digests(plan.digest), label="digest")
            with pytest.raises(IntakeRefusedError) as refused:
                await world.import_sheet(BENCH, text, digest)
            assert refused.value.problems == plan.problems
        else:
            digest = changed_since(world, plan, data)
            before = stores(world)
            with pytest.raises(ImportChangedError):
                await world.import_sheet(BENCH, text, digest)
        assert stores(world) == before

    anyio.run(scenario)


# --- Property 5 ----------------------------------------------------------------------------------

type Pair = tuple[PartId, LocationId]


def part_ids(plan: ImportPlan, result: ImportResult) -> dict[int, PartId]:
    """The part each row stocked, by row: the one it defined, named, or repeated."""
    defined = {imported.row: imported.part.id for imported in result.parts}
    ids: dict[int, PartId] = {}
    for row in plan.rows:
        if isinstance(row.part, NamesPart):
            ids[row.row] = row.part.part.id
        elif isinstance(row.part, SameAsRow):
            ids[row.row] = ids[row.part.row]
        else:
            ids[row.row] = defined[row.row]
    return ids


def count_of(stock: StockOutcome) -> int:
    return int(stock.quantity) if isinstance(stock, ReceivesLot) else len(stock.units)


def planned_receipts(plan: ImportPlan, ids: Mapping[int, PartId]) -> Counter[Pair]:
    """How much the plan puts into each (part, location) lot."""
    planned: Counter[Pair] = Counter()
    for row in plan.rows:
        if row.stock is not None:
            planned[ids[row.row], row.stock.location.id] += count_of(row.stock)
    return planned


def planned_units(plan: ImportPlan, ids: Mapping[int, PartId]) -> Counter[tuple[object, ...]]:
    """Every unit the plan mints: its part, its location and its labels."""
    return Counter(
        (ids[row.row], row.stock.location.id, labels.serial, labels.mac)
        for row in plan.rows
        if isinstance(row.stock, ReceivesUnits)
        for labels in row.stock.units
    )


def on_hand_by_pair(world: World) -> dict[Pair, int]:
    lots = world.inventory.lots.saved
    return {
        (lots[lot_id].part_id, lots[lot_id].location_id): int(balance.on_hand)
        for lot_id, balance in world.inventory.balances.saved.items()
    }


def minted_since(world: World, before: Mapping[UnitId, Unit]) -> list[tuple[object, ...]]:
    lots = world.inventory.lots.saved
    return [
        (unit.part_id, lots[unit.lot_id].location_id, unit.serial, unit.mac)
        for unit_id, unit in world.inventory.units.saved.items()
        if unit_id not in before
    ]


async def assert_ledger_agrees(world: World, pairs: Counter[Pair], tracked: set[Pair]) -> None:
    """Every lot touched: on_hand is its ledger's sum and, for units, its in-stock units."""
    for part_id, location_id in pairs:
        lot = await world.inventory.lots.for_part_at(part_id, location_id)
        assert lot is not None
        held = await on_hand(world, part_id, location_id)
        movements = await world.inventory.ledger.movements_of(lot.id)
        assert sum(movement.change for movement in movements) == held
        if (part_id, location_id) in tracked:
            assert await world.inventory.units.in_stock_at(lot.id) == held


async def assert_again_defines_no_numbered_part(world: World, text: str, first: ImportPlan) -> None:
    """The same sheet again names every part it gave a part number, and defines only the
    rows without one. Its labels are the stored units' now, so a labelled sheet is refused."""
    again = await world.preview_import(BENCH, text)
    unnumbered = [
        row.row
        for row in first.rows
        if isinstance(row.part, DefinesPart) and row.part.identity is None
    ]
    assert [row.row for row in again.rows if isinstance(row.part, DefinesPart)] == unnumbered
    assert all(isinstance(row.part, NamesPart) for row in again.rows if row.row not in unnumbered)
    if again.problems:
        taken = {ProblemCode.SERIAL_TAKEN, ProblemCode.MAC_TAKEN}
        assert {problem.code for problem in again.problems} <= taken
        return
    defined = len(world.inventory.catalog.defined)
    result = await world.import_sheet(BENCH, text, again.digest)
    assert [imported.row for imported in result.parts] == unnumbered
    assert len(world.inventory.catalog.defined) == defined + len(unnumbered)


@given(start=_STARTS, text=clean_sheets())
def test_an_import_does_exactly_what_its_preview_showed(start: Start, text: str) -> None:
    """Property 5: an import does exactly what its preview showed.

    A clean preview, imported with its digest, defines exactly the parts it marked new, in
    row order; raises each (part, location) lot's on_hand by exactly what it planned there
    and nothing else's; mints exactly the planned units with their labels; writes one
    RECEIVE per row with stock; and commits once. Afterwards every lot it touched agrees
    with its ledger and, for units, with its in-stock units; and the same sheet imported
    again defines none of its part-numbered parts again.

    **Validates: Requirements 5.1, 5.2, 6.1, 6.2, 8.1, 8.6, 8.7**
    """

    async def scenario() -> None:
        world = await bench(start)
        plan = await world.preview_import(BENCH, text)
        assert plan.problems == ()
        stocked_before = on_hand_by_pair(world)
        units_before = dict(world.inventory.units.saved)
        ledger_before = len(world.inventory.ledger.saved)

        result = await world.import_sheet(BENCH, text, plan.digest)

        new = [(row.row, row.part) for row in plan.rows if isinstance(row.part, DefinesPart)]
        assert world.inventory.catalog.defined == [part.draft for _, part in new]
        assert [imported.row for imported in result.parts] == [number for number, _ in new]
        ids = part_ids(plan, result)
        planned = planned_receipts(plan, ids)
        stocked = on_hand_by_pair(world)
        raised = {
            pair: held - stocked_before.get(pair, 0)
            for pair, held in stocked.items()
            if held != stocked_before.get(pair, 0)
        }
        assert raised == dict(planned)
        assert Counter(minted_since(world, units_before)) == planned_units(plan, ids)
        assert list(result.units) == [
            unit
            for unit_id, unit in world.inventory.units.saved.items()
            if unit_id not in units_before
        ]
        receipts = [count_of(row.stock) for row in plan.rows if row.stock is not None]
        movements = world.inventory.ledger.saved[ledger_before:]
        assert [(m.kind, m.change) for m in movements] == [
            (MovementKind.RECEIVE, change) for change in receipts
        ]
        assert result.summary == plan.summary
        assert world.inventory.commits == 1
        tracked = {
            (ids[row.row], row.stock.location.id)
            for row in plan.rows
            if isinstance(row.stock, ReceivesUnits)
        }
        await assert_ledger_agrees(world, planned, tracked)
        await assert_again_defines_no_numbered_part(world, text, plan)

    anyio.run(scenario)


# --- Property 7 ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Typed:
    """A quick-add as typed, and the one row of a sheet that says the same: the category by
    its path, the stock's location by its short code."""

    category: str | None  # a category's path, or one no category has
    name: str | None
    manufacturer: str | None
    mpn: str | None
    package: str | None
    attributes: tuple[tuple[str, str], ...]
    stock: tuple[str, int] | None  # a location's code and a quantity

    def cells(self) -> dict[str, str]:
        given = {
            Column.CATEGORY: self.category,
            Column.NAME: self.name,
            Column.MANUFACTURER: self.manufacturer,
            Column.MPN: self.mpn,
            Column.PACKAGE: self.package,
            **dict(self.attributes),
        }
        if self.stock is not None:
            given |= {Column.LOCATION: self.stock[0], Column.QUANTITY: str(self.stock[1])}
        return {column: cell for column, cell in given.items() if cell is not None}


# Cells that aren't blank, holding separators, quotes and line breaks the sheet has to quote.
_CELL_TEXT = st.text(st.sampled_from('ab 7kΩµã,;"/\n'), min_size=1, max_size=8).filter(str.strip)
_OPTIONAL_CELL = st.none() | _CELL_TEXT
_CODES = ("WX-L-0001", "WX-L-0002", "WX-L-0099")  # the last is no location's
_QUANTITIES = st.sampled_from([0, 1, 100, 101, 1_000_000, 1_000_001]) | st.integers(-3, 120)

# A one-row sheet needs a row: a quick-add with nothing typed has no sheet to agree with.
_TYPED = st.builds(
    Typed,
    category=st.sampled_from([None, "Passives / Resistors", "Boards", "Sensors", "Nowhere"]),
    name=_OPTIONAL_CELL,
    manufacturer=_OPTIONAL_CELL,
    mpn=_OPTIONAL_CELL,
    package=_OPTIONAL_CELL,
    attributes=st.dictionaries(
        st.sampled_from(["tolerance", "i2c_address"]), _CELL_TEXT, max_size=2
    ).map(lambda attributes: tuple(sorted(attributes.items()))),
    stock=st.none() | st.tuples(st.sampled_from(_CODES), _QUANTITIES),
).filter(lambda typed: bool(typed.cells()))


def quick_addition(world: World, typed: Typed) -> QuickAddition:
    """The quick-add the web would send: the category and location picked by id, one no
    workspace holds for a path or a code that names nothing."""
    categories = world.inventory.catalog.categories.values()
    category: UUID | None = None
    if typed.category is not None:
        category = next((c.id for c in categories if c.path == typed.category), uuid7())
    draft = PartDraft(
        category_id=category,
        name=typed.name,
        manufacturer=typed.manufacturer,
        mpn=typed.mpn,
        package=typed.package,
        attributes=dict(typed.attributes),
    )
    if typed.stock is None:
        return QuickAddition(draft)
    code, quantity = typed.stock
    locations = world.inventory.locations.saved.values()
    location = next((loc.id for loc in locations if str(loc.code) == code), LocationId(uuid7()))
    return QuickAddition(draft, QuickStock(location, quantity))


async def quick_added(world: World, typed: Typed) -> QuickAdded | IntakeRefusedError:
    try:
        return await world.quick_add(BENCH, quick_addition(world, typed))
    except IntakeRefusedError as refused:
        return refused


def written(world: World) -> tuple[object, ...]:
    """What an intake wrote, in terms two benches share: the drafts defined with their
    category by path, the parts, each lot by its location's code, the ledger and the units."""
    inventory = world.inventory
    categories = inventory.catalog.categories
    drafts = [
        draft
        if draft.category_id is None
        else replace(draft, category_id=None, category_path=categories[draft.category_id].path)
        for draft in inventory.catalog.defined
    ]
    parts = [(part.name, part.tracked_individually) for part in inventory.catalog.parts.values()]
    places = inventory.locations.saved
    lots = sorted(
        (str(places[inventory.lots.saved[lot_id].location_id].code), int(balance.on_hand))
        for lot_id, balance in inventory.balances.saved.items()
    )
    ledger = [(movement.kind, movement.change) for movement in inventory.ledger.saved]
    units = [(str(unit.code), unit.serial, unit.mac) for unit in inventory.units.saved.values()]
    return drafts, parts, lots, ledger, units


@given(typed=_TYPED)
def test_quick_add_agrees_with_a_one_row_import(typed: Typed) -> None:
    """Property 7: quick-add agrees with a one-row import.

    On two benches alike, a quick-add succeeds exactly when the one-row sheet of the same
    values previews clean. When both do, they write the same part and the same stock. When
    the quick-add is refused, it reports the same problems as the preview, by column and
    code (the row aside, and the sentences, since quick-add names a location by id), and
    leaves every store as it was.

    **Validates: Requirements 1.1, 1.4, 1.5, 1.8, 5.3**
    """

    async def scenario() -> None:
        quick, imported = await bench(_EMPTY), await bench(_EMPTY)
        before = stores(quick)
        added = await quick_added(quick, typed)
        text = text_of([typed.cells()])
        plan = await imported.preview_import(BENCH, text)

        if isinstance(added, IntakeRefusedError):
            assert plan.problems != ()
            assert [(p.column, p.code) for p in added.problems] == [
                (p.column, p.code) for p in plan.problems
            ]
            assert stores(quick) == before
            return
        assert plan.problems == ()
        await imported.import_sheet(BENCH, text, plan.digest)
        assert written(quick) == written(imported)

    anyio.run(scenario)
