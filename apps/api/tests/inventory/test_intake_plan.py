"""The plan of an intake: a row's stock, the quantity rule, what a sheet has planned so far,
the sheet's unit cap, the summary and the digest.

`plan_stock` is tested over rows as the sheet reader makes them and a small bench of
locations. Property 6, the digest following what the plan will do, is the last two tests:
over plans built from what their rows do, and over sheets spelled several ways.
"""

import hashlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import UUID, uuid7

import pytest
from hypothesis import given
from hypothesis import strategies as st

from wiredex.inventory.domain.intake import (
    MAX_LOT_QUANTITY,
    MAX_SHEET_UNITS,
    MAX_UNITS_PER_RECEIPT,
    CellProblem,
    DefinesPart,
    ImportPlan,
    ImportSummary,
    KnownPart,
    NamesPart,
    PartDraft,
    PlannedRow,
    ProblemCode,
    ReceivesLot,
    ReceivesUnits,
    SameAsRow,
    SheetBook,
    UnitLabels,
    plan_stock,
    quantity_problem,
)
from wiredex.inventory.domain.location import Location, LocationPaths
from wiredex.inventory.domain.sheet import (
    SEPARATORS,
    Column,
    Sheet,
    SheetRow,
    read_sheet,
    write_sheet,
)
from wiredex.inventory.domain.values import (
    LocationId,
    LocationName,
    Mac,
    PartId,
    Quantity,
    Serial,
    ShortCode,
    WorkspaceId,
)

NOW = datetime(2026, 9, 27, 10, 0, tzinfo=UTC)
BENCH = WorkspaceId(uuid7())


def place(name: str, number: int, parent: Location | None = None) -> Location:
    parent_id = None if parent is None else parent.id
    code = ShortCode.for_location(number)
    return Location(LocationId(uuid7()), BENCH, parent_id, code, LocationName(name), NOW)


# Lab → Drawer 3 (WX-L-0003), Lab → Parts box, and a Bin in each of two cabinets.
LAB = place("Lab", 1)
PARTS_BOX = place("Parts box", 2, LAB)
DRAWER = place("Drawer 3", 3, LAB)
CABINET_A = place("Cabinet A", 4, LAB)
BIN_A = place("Bin", 5, CABINET_A)
CABINET_B = place("Cabinet B", 6, LAB)
BIN_B = place("Bin", 7, CABINET_B)
LOCATIONS = LocationPaths([LAB, PARTS_BOX, DRAWER, CABINET_A, BIN_A, CABINET_B, BIN_B])

ESP32 = KnownPart(PartId(uuid7()), "ESP32 DevKit", tracked_individually=True, not_stocked=False)
RESISTOR = KnownPart(PartId(uuid7()), "10k 0805", tracked_individually=False, not_stocked=False)


def row(number: int = 2, /, **cells: str) -> SheetRow:
    """A row as the reader makes it, keyed by the columns' values: `location`, `quantity`…"""
    return SheetRow(number, cells, overflows=False)


def blank_units(count: int) -> tuple[UnitLabels, ...]:
    return (UnitLabels(None, None),) * count


def codes_of(problems: Sequence[CellProblem]) -> list[tuple[str | None, ProblemCode]]:
    return [(problem.column, problem.code) for problem in problems]


# --- plan_stock: a lot or units ---------------------------------------------------------------


def test_a_lot_counted_part_receives_one_lot() -> None:
    # Requirement 6.1.
    stock = plan_stock(row(location="WX-L-0003", quantity="200"), False, False, LOCATIONS)

    assert stock == (ReceivesLot(DRAWER, Quantity(200)), ())


def test_a_unit_tracked_part_receives_that_many_blank_units() -> None:
    # Requirement 6.2: each unit gets a blank serial and MAC.
    stock = plan_stock(row(location="WX-L-0003", quantity="3"), True, False, LOCATIONS)

    assert stock == (ReceivesUnits(DRAWER, blank_units(3)), ())


def test_a_location_is_found_by_its_path_as_well_as_its_code() -> None:
    stock, problems = plan_stock(
        row(location=" lab / parts BOX ", quantity="5"), False, False, LOCATIONS
    )

    assert stock == ReceivesLot(PARTS_BOX, Quantity(5))
    assert problems == ()


@pytest.mark.parametrize("quantity", ["", "1", " 1 ", "01"])
def test_a_serial_labels_one_unit_whose_quantity_is_blank_or_one(quantity: str) -> None:
    # Requirement 6.3.
    cells = row(location="WX-L-0003", quantity=quantity, serial=" SN  0001 ")

    stock = plan_stock(cells, True, False, LOCATIONS)

    assert stock == (ReceivesUnits(DRAWER, (UnitLabels(Serial("SN 0001"), None),)), ())


def test_a_mac_in_any_accepted_spelling_is_planned_canonical() -> None:
    # Requirement 6.10: 06's spellings, kept as the value object normalizes them.
    stock, problems = plan_stock(
        row(location="WX-L-0003", mac="AABB.CCDD.EEFF"), True, False, LOCATIONS
    )

    assert problems == ()
    assert isinstance(stock, ReceivesUnits)
    assert str(stock.units[0].mac) == "aa:bb:cc:dd:ee:ff"


def test_a_mac_that_is_not_six_hex_octets_is_refused() -> None:
    stock, problems = plan_stock(row(location="WX-L-0003", mac="aa:bb:cc"), True, False, LOCATIONS)

    assert stock is None
    assert codes_of(problems) == [(Column.MAC, ProblemCode.BAD_MAC)]
    assert "six hex octets" in problems[0].message


def test_a_serial_its_value_object_refuses_is_refused() -> None:
    _, problems = plan_stock(row(location="WX-L-0003", serial="S" * 81), True, False, LOCATIONS)

    assert codes_of(problems) == [(Column.SERIAL, ProblemCode.BAD_SERIAL)]


@pytest.mark.parametrize("quantity", ["2", "0", "twelve"])
def test_a_label_beside_any_other_quantity_is_refused(quantity: str) -> None:
    cells = row(location="WX-L-0003", quantity=quantity, serial="SN-0001")

    stock, problems = plan_stock(cells, True, False, LOCATIONS)

    assert stock is None
    assert codes_of(problems) == [(Column.QUANTITY, ProblemCode.ONE_UNIT_PER_LABEL)]


@pytest.mark.parametrize(
    ("labels", "column"),
    [
        ({"serial": "SN-0001"}, Column.SERIAL),
        ({"mac": "aa:bb:cc:dd:ee:ff"}, Column.MAC),
        ({"serial": "SN-0001", "mac": "aa:bb:cc:dd:ee:ff"}, Column.SERIAL),
    ],
)
def test_a_label_on_a_part_counted_in_lots_is_refused(labels: dict[str, str], column: str) -> None:
    # Requirement 6.4.
    stock, problems = plan_stock(row(location="WX-L-0003", **labels), False, False, LOCATIONS)

    assert stock is None
    assert codes_of(problems) == [(column, ProblemCode.COUNTED_IN_LOTS)]
    assert "counted in lots" in problems[0].message


def test_a_label_on_a_lot_still_has_its_quantity_read_as_a_lots() -> None:
    cells = row(location="WX-L-0003", quantity="12 pcs", serial="SN-0001")

    _, problems = plan_stock(cells, False, False, LOCATIONS)

    assert codes_of(problems) == [
        (Column.QUANTITY, ProblemCode.BAD_QUANTITY),
        (Column.SERIAL, ProblemCode.COUNTED_IN_LOTS),
    ]


# --- plan_stock: the pair, and nothing given ---------------------------------------------------


_NO_LOCATION = (Column.LOCATION, ProblemCode.LOCATION_NEEDED)
_NO_QUANTITY = (Column.QUANTITY, ProblemCode.QUANTITY_NEEDED)


@pytest.mark.parametrize(
    ("cells", "tracked", "expected"),
    [
        pytest.param({"quantity": "5"}, False, _NO_LOCATION, id="a quantity alone"),
        pytest.param({"location": "WX-L-0003"}, False, _NO_QUANTITY, id="a location alone"),
        pytest.param({"location": "WX-L-0003"}, True, _NO_QUANTITY, id="the same, for units"),
        pytest.param({"serial": "SN-0001"}, True, _NO_LOCATION, id="a serial alone"),
        pytest.param({"mac": "aa:bb:cc:dd:ee:ff"}, True, _NO_LOCATION, id="a mac alone"),
    ],
)
def test_one_of_the_pair_without_the_other_is_missing_the_other(
    cells: dict[str, str], tracked: bool, expected: tuple[str, ProblemCode]
) -> None:
    # Requirement 6.6.
    stock, problems = plan_stock(row(**cells), tracked, False, LOCATIONS)

    assert stock is None
    assert codes_of(problems) == [expected]


@pytest.mark.parametrize("tracked", [True, False, None])
def test_a_row_with_no_stock_cells_plans_no_stock(tracked: bool | None) -> None:
    # Requirement 6.7: blank cells are nothing given, and so is a column the sheet lacks.
    cells = row(name="10k", location="  ", quantity="", serial="\t")

    assert plan_stock(cells, tracked, False, LOCATIONS) == (None, ())
    assert plan_stock(row(name="10k"), tracked, False, LOCATIONS) == (None, ())


# --- plan_stock: a consumable takes no stock ------------------------------------------------


@pytest.mark.parametrize(
    ("cells", "column"),
    [
        pytest.param({"quantity": "5", "location": "WX-L-0003"}, Column.QUANTITY, id="quantity"),
        pytest.param({"location": "Nowhere", "serial": "S-1"}, Column.LOCATION, id="location"),
        pytest.param({"serial": "S" * 81, "mac": "zz"}, Column.SERIAL, id="serial"),
        pytest.param({"mac": "aa:bb:cc:dd:ee:ff"}, Column.MAC, id="mac"),
    ],
)
@pytest.mark.parametrize("tracked", [True, False])
def test_stock_given_to_a_consumable_is_one_problem_on_its_first_stock_cell(
    cells: dict[str, str], column: Column, tracked: bool
) -> None:
    # 09's requirement 2.5: in the order quantity, location, serial, MAC, whatever the cells
    # hold and however the part is counted, and no stock is planned.
    stock, problems = plan_stock(row(4, **cells), tracked, True, LOCATIONS)

    assert stock is None
    assert codes_of(problems) == [(column, ProblemCode.NOT_STOCKED)]
    assert problems[0].row == 4


def test_a_consumable_without_stock_cells_plans_no_stock_and_no_problem() -> None:
    # 09's requirement 2.6.
    assert plan_stock(row(name="Hook-up wire", location=" "), False, True, LOCATIONS) == (None, ())


# --- plan_stock: the cells that don't read ---------------------------------------------------


@pytest.mark.parametrize("quantity", ["1,000", "12 pcs", "-3", "+3", "1_000", "2.5"])
def test_a_quantity_that_isnt_written_in_digits_is_refused(quantity: str) -> None:
    # `int()` would take `+3` and `1_000`; a spreadsheet's quantity never means them.
    stock, problems = plan_stock(
        row(location="WX-L-0003", quantity=quantity), False, False, LOCATIONS
    )

    assert stock is None
    assert codes_of(problems) == [(Column.QUANTITY, ProblemCode.BAD_QUANTITY)]
    assert repr(quantity) in problems[0].message


@pytest.mark.parametrize(
    ("quantity", "tracked", "code"),
    [
        ("101", True, ProblemCode.TOO_MANY_UNITS),
        ("1000001", False, ProblemCode.BAD_QUANTITY),
        ("0", False, ProblemCode.BAD_QUANTITY),
        # Too long for int() to convert: past every cap, and refused rather than a crash.
        ("9" * 5_000, False, ProblemCode.BAD_QUANTITY),
        ("9" * 5_000, True, ProblemCode.TOO_MANY_UNITS),
    ],
    ids=["101 units", "a lot past a million", "zero", "thousands of digits", "as many units"],
)
def test_a_quantity_out_of_range_is_refused(quantity: str, tracked: bool, code: str) -> None:
    # Requirement 6.8.
    _, problems = plan_stock(
        row(location="WX-L-0003", quantity=quantity), tracked, False, LOCATIONS
    )

    assert codes_of(problems) == [(Column.QUANTITY, code)]


def test_leading_zeros_are_still_a_whole_number() -> None:
    stock, _ = plan_stock(row(location="WX-L-0003", quantity="0000200"), False, False, LOCATIONS)

    assert stock == ReceivesLot(DRAWER, Quantity(200))


def test_a_location_no_code_or_path_names_is_unknown() -> None:
    _, problems = plan_stock(row(location="Nowhere", quantity="5"), False, False, LOCATIONS)

    assert codes_of(problems) == [(Column.LOCATION, ProblemCode.UNKNOWN_LOCATION)]
    assert "'Nowhere'" in problems[0].message


def test_a_location_two_paths_end_with_is_ambiguous_naming_both() -> None:
    _, problems = plan_stock(row(location="bin", quantity="5"), False, False, LOCATIONS)

    assert codes_of(problems) == [(Column.LOCATION, ProblemCode.AMBIGUOUS_LOCATION)]
    assert "Lab / Cabinet A / Bin or Lab / Cabinet B / Bin" in problems[0].message


def test_every_stock_problem_is_reported_at_once_on_its_row() -> None:
    cells = row(7, location="Nowhere", quantity="3", serial="S" * 81, mac="zz")

    stock, problems = plan_stock(cells, True, False, LOCATIONS)

    assert stock is None
    assert codes_of(problems) == [
        (Column.LOCATION, ProblemCode.UNKNOWN_LOCATION),
        (Column.QUANTITY, ProblemCode.ONE_UNIT_PER_LABEL),
        (Column.SERIAL, ProblemCode.BAD_SERIAL),
        (Column.MAC, ProblemCode.BAD_MAC),
    ]
    assert {problem.row for problem in problems} == {7}


def test_with_the_kind_unknown_nothing_is_planned_but_problems_are_reported() -> None:
    # The category is the row's problem; the stock cells are still checked for what holds
    # whichever kind the part turns out to be.
    assert plan_stock(row(location="WX-L-0003", quantity="500"), None, False, LOCATIONS) == (
        None,
        (),
    )

    _, problems = plan_stock(row(location="Nowhere", quantity="-3"), None, False, LOCATIONS)

    assert codes_of(problems) == [
        (Column.LOCATION, ProblemCode.UNKNOWN_LOCATION),
        (Column.QUANTITY, ProblemCode.BAD_QUANTITY),
    ]


# --- quantity_problem: the one quantity rule ---------------------------------------------------


@pytest.mark.parametrize(
    ("quantity", "tracked", "code"),
    [
        (0, False, ProblemCode.BAD_QUANTITY),
        (1, False, None),
        (100, False, None),
        (101, False, None),
        (1_000_000, False, None),
        (1_000_001, False, ProblemCode.BAD_QUANTITY),
        (0, True, ProblemCode.BAD_QUANTITY),
        (1, True, None),
        (100, True, None),
        (101, True, ProblemCode.TOO_MANY_UNITS),
        (1_000_000, True, ProblemCode.TOO_MANY_UNITS),
        (1_000_001, True, ProblemCode.TOO_MANY_UNITS),
        # The kind still unknown: only what holds for both.
        (0, None, ProblemCode.BAD_QUANTITY),
        (101, None, None),
        (1_000_001, None, ProblemCode.BAD_QUANTITY),
        (-1, False, ProblemCode.BAD_QUANTITY),
    ],
)
def test_the_quantity_rule_at_its_bounds(
    quantity: int, tracked: bool | None, code: ProblemCode | None
) -> None:
    # Requirements 1.8 and 6.8: 1 to 1,000,000 of a lot, 1 to 100 units.
    problem = quantity_problem(quantity, tracked)

    assert (None if problem is None else problem.code) == code
    if problem is not None:
        assert (problem.row, problem.column) == (None, Column.QUANTITY)


@pytest.mark.parametrize(
    ("quantity", "tracked", "says"),
    [
        (0, False, "from 1 to 1,000,000"),
        (0, True, "from 1 to 100"),
        (0, None, "from 1 to 1,000,000"),
        (101, True, "at most 100 units"),
    ],
)
def test_the_quantity_rule_says_the_range_it_holds(
    quantity: int, tracked: bool | None, says: str
) -> None:
    problem = quantity_problem(quantity, tracked)

    assert problem is not None
    assert says in problem.message


# --- PartDraft: a row's part cells ------------------------------------------------------------


def test_a_rows_draft_takes_its_part_cells_and_drops_the_blank_ones() -> None:
    # Requirement 5.6: a blank attribute cell is an attribute not given.
    cells = row(
        category="Resistors",
        name=" 10k ",
        manufacturer="",
        mpn="RC0805FR-0710KL",
        package="  ",
        location="WX-L-0003",
        quantity="5",
        resistance="10k",
        tolerance="",
    )

    assert PartDraft.of_row(cells) == PartDraft(
        category_path="Resistors",
        name=" 10k ",
        mpn="RC0805FR-0710KL",
        attributes={"resistance": "10k"},
    )


def test_a_draft_reads_columns_by_name_whatever_the_headers_language() -> None:
    sheet = read_sheet("quantidade;nome;categoria;tolerance\n5;10k;Resistors;1%\n")

    assert PartDraft.of_row(sheet.rows[0]) == PartDraft(
        category_path="Resistors", name="10k", attributes={"tolerance": "1%"}
    )


# --- SheetBook: what a sheet has planned so far -----------------------------------------------


def test_the_first_row_to_give_an_identity_is_the_one_later_rows_name() -> None:
    # Requirement 5.2.
    book = SheetBook()

    assert book.part_row("bosch\nbme280", 2) == 2
    assert book.part_row("bosch\nbme280", 5) == 2
    assert book.part_row("\nbme280", 6) == 6  # without a manufacturer, another part


def test_a_row_without_an_identity_is_a_part_of_its_own() -> None:
    # Requirement 5.8: no part number, a new part, whatever other rows hold.
    book = SheetBook()

    assert book.part_row(None, 3) == 3
    assert book.part_row(None, 4) == 4


def test_a_serial_an_earlier_row_gives_the_same_part_is_refused_naming_that_row() -> None:
    # Requirement 6.9, compared case-folded as the unique index compares it.
    book = SheetBook()

    assert book.label_problems(2, UnitLabels(Serial("SN-0001"), None), 2) == ()
    assert book.label_problems(2, UnitLabels(Serial("sn-0001"), None), 4) == (
        CellProblem(
            4,
            Column.SERIAL,
            ProblemCode.SERIAL_TAKEN,
            "row 2 already gives this part the serial sn-0001",
        ),
    )


def test_the_same_serial_on_another_part_is_allowed() -> None:
    book = SheetBook()
    book.label_problems(2, UnitLabels(Serial("SN-0001"), None), 2)

    assert book.label_problems(3, UnitLabels(Serial("SN-0001"), None), 3) == ()


def test_a_mac_an_earlier_row_gives_any_part_is_refused_naming_that_row() -> None:
    book = SheetBook()
    book.label_problems(2, UnitLabels(None, Mac("aa:bb:cc:dd:ee:ff")), 2)

    problems = book.label_problems(9, UnitLabels(Serial("SN-9"), Mac("AA-BB-CC-DD-EE-FF")), 9)

    assert codes_of(problems) == [(Column.MAC, ProblemCode.MAC_TAKEN)]
    assert problems[0].row == 9
    assert problems[0].message == "row 2 already has the MAC aa:bb:cc:dd:ee:ff"


# --- ImportPlan: the unit cap, the problems and the summary -----------------------------------


def units_row(number: int, count: int) -> PlannedRow:
    return PlannedRow(number, NamesPart(ESP32), ReceivesUnits(DRAWER, blank_units(count)), ())


def test_a_sheet_may_plan_its_cap_of_units() -> None:
    plan = ImportPlan.of(units_row(number, 100) for number in range(2, 7))

    assert plan.summary.units == MAX_SHEET_UNITS
    assert plan.sheet_problems == ()


def test_one_unit_past_the_sheets_cap_is_a_problem_of_the_sheet_as_a_whole() -> None:
    # Requirement 6.11.
    rows = [*(units_row(number, 100) for number in range(2, 7)), units_row(7, 1)]

    plan = ImportPlan.of(rows)

    assert codes_of(plan.sheet_problems) == [(None, ProblemCode.SHEET_TOO_MANY_UNITS)]
    assert plan.sheet_problems[0].row is None
    assert "plans 501" in plan.sheet_problems[0].message
    assert plan.problems == plan.sheet_problems


def test_a_plans_problems_are_the_sheets_then_every_rows_in_order() -> None:
    first = CellProblem(3, Column.NAME, ProblemCode.MISSING, "a new part needs a name")
    second = CellProblem(5, Column.LOCATION, ProblemCode.UNKNOWN_LOCATION, "no")
    sheet = CellProblem(None, None, ProblemCode.SHEET_TOO_MANY_UNITS, "too many")
    rows = (
        PlannedRow(3, SameAsRow(2, False, False), None, (first,)),
        PlannedRow(5, NamesPart(RESISTOR), None, (second,)),
    )

    assert ImportPlan(rows, (sheet,)).problems == (sheet, first, second)


def test_the_summary_counts_what_the_rows_will_do() -> None:
    # Requirement 7.3. A stored part named twice is one existing part.
    new = DefinesPart(PartDraft(name="10k"), uuid7(), "Passives / Resistors", None, False, False)
    missing = CellProblem(8, Column.NAME, ProblemCode.MISSING, "a new part needs a name")
    rows = [
        PlannedRow(2, new, None, ()),
        PlannedRow(3, new, ReceivesLot(DRAWER, Quantity(200)), ()),
        PlannedRow(4, NamesPart(RESISTOR), ReceivesLot(DRAWER, Quantity(30)), ()),
        PlannedRow(5, NamesPart(RESISTOR), ReceivesLot(PARTS_BOX, Quantity(5)), ()),
        PlannedRow(6, NamesPart(ESP32), ReceivesUnits(DRAWER, blank_units(3)), ()),
        PlannedRow(7, SameAsRow(3, False, False), ReceivesLot(DRAWER, Quantity(10)), ()),
        PlannedRow(8, replace(new, draft=PartDraft()), None, (missing,)),
    ]

    assert ImportPlan.of(rows).summary == ImportSummary(
        rows=7,
        new_parts=3,
        existing_parts=2,
        receipts=4,
        pieces=245,
        units=3,
        rows_with_problems=1,
    )


def test_an_empty_plan_summarizes_to_nothing() -> None:
    assert ImportPlan.of([]).summary == ImportSummary(0, 0, 0, 0, 0, 0, 0)


# --- The digest's canonical form ---------------------------------------------------------------


def test_the_digest_is_the_sha256_of_the_rows_canonical_json() -> None:
    # Pinned to the form design.md documents, so a change to it is a deliberate one.
    category = UUID("0199aaaa-0000-7000-8000-000000000001")
    draft = PartDraft(
        category_path="Resistors",
        name=" 10k ",
        mpn="RC0805",
        attributes={"tolerance": " 1% ", "resistance": "10k", "smd": True},
    )
    labels = (UnitLabels(Serial("SN-1"), Mac("AA-BB-CC-DD-EE-FF")), UnitLabels(None, None))
    rows = (
        PlannedRow(2, DefinesPart(draft, category, "Passives", "\nrc0805", False, False), None, ()),
        PlannedRow(3, NamesPart(ESP32), ReceivesUnits(DRAWER, labels), ()),
        PlannedRow(4, SameAsRow(2, False, False), ReceivesLot(PARTS_BOX, Quantity(5)), ()),
    )
    expected = (
        f'[[2,["defines","{category}","\\nrc0805","10k",null,"RC0805",null,'
        f'[["resistance","10k"],["smd",true],["tolerance","1%"]]],null],'
        f'[3,["names","{ESP32.id}"],["units","{DRAWER.id}",'
        f'[["SN-1","aa:bb:cc:dd:ee:ff"],[null,null]]]],'
        f'[4,["same_as",2],["lot","{PARTS_BOX.id}",5]]]'
    )

    digest = ImportPlan.of(rows).digest

    assert digest == hashlib.sha256(expected.encode()).hexdigest()


def test_any_text_a_cell_can_hold_has_a_digest() -> None:
    # A JSON body can carry a lone surrogate; escaped, it still encodes.
    draft = PartDraft(name="\ud800 10k", attributes={"note": "µ\u2028"})
    rows = (PlannedRow(2, DefinesPart(draft, None, None, None, None, None), None, ()),)

    assert len(ImportPlan.of(rows).digest) == 64


def test_the_problem_codes_are_the_designs() -> None:
    # The web has a sentence for each; the first five are catalog's DraftProblemKind.
    assert [code.value for code in ProblemCode] == [
        "unknown_category",
        "ambiguous_category",
        "missing",
        "invalid",
        "not_an_attribute",
        "unknown_location",
        "ambiguous_location",
        "location_needed",
        "quantity_needed",
        "bad_quantity",
        "too_many_units",
        "counted_in_lots",
        "one_unit_per_label",
        "bad_serial",
        "bad_mac",
        "serial_taken",
        "mac_taken",
        "extra_cells",
        "sheet_too_many_units",
        "not_stocked",
        "part_in_trash",
    ]


# --- Property 6: the digest follows what the plan will do --------------------------------------
#
# First over plans. What a row does is written as plain data, the model the digest has to
# follow: the part it resolves to (a new part's category and cells, a stored part, an earlier
# row) and the stock it receives (a location and a quantity, or a location and each unit's
# labels). A plan is then built from that model with everything that doesn't change what it
# does drawn at random: problems, the paths and flags shown, a part's or a location's name,
# spacing around a cell, a MAC's spelling, the order attributes were typed in.

CATEGORY_IDS = (uuid7(), uuid7())
PART_IDS = (PartId(uuid7()), PartId(uuid7()))
PLACES = (DRAWER, PARTS_BOX, BIN_A)

_TEXT = st.sampled_from(["10k", "4k7", "BME280"])
_OPTIONAL_TEXT = st.none() | _TEXT
_SERIALS = ("SN-1", "sn-1", "SN 2")
_MACS = ("aa:bb:cc:dd:ee:01", "aa:bb:cc:dd:ee:02")
_GAPS = st.sampled_from(["", " ", "\t", "  "])


@dataclass(frozen=True)
class NewPart:
    category: int | None  # an index into CATEGORY_IDS; None while it is a problem
    name: str | None
    manufacturer: str | None
    mpn: str | None
    package: str | None
    attributes: tuple[tuple[str, str | bool], ...]  # sorted by key


@dataclass(frozen=True)
class StoredPart:
    part: int  # an index into PART_IDS


@dataclass(frozen=True)
class EarlierRow:
    row: int


@dataclass(frozen=True)
class Lot:
    location: int  # an index into PLACES
    quantity: int


@dataclass(frozen=True)
class Units:
    location: int
    labels: tuple[tuple[str | None, str | None], ...]  # a serial as kept, a canonical MAC


@dataclass(frozen=True)
class Doing:
    """What one row does, and nothing else."""

    part: NewPart | StoredPart | EarlierRow
    stock: Lot | Units | None


def sorted_attributes(attributes: Mapping[str, str | bool]) -> tuple[tuple[str, str | bool], ...]:
    return tuple((key, attributes[key]) for key in sorted(attributes))


# `true` beside True: text and a yes-or-no are different values, and JSON keeps them apart.
_ATTRIBUTE_VALUES: tuple[str | bool, ...] = ("10k", "1%", "true", True, False)
_ATTRIBUTES = st.dictionaries(
    st.sampled_from(["resistance", "tolerance", "smd"]),
    st.sampled_from(_ATTRIBUTE_VALUES),
    max_size=2,
).map(sorted_attributes)

_NEW_PARTS = st.builds(
    NewPart,
    st.none() | st.integers(0, len(CATEGORY_IDS) - 1),
    _OPTIONAL_TEXT,
    _OPTIONAL_TEXT,
    _OPTIONAL_TEXT,
    _OPTIONAL_TEXT,
    _ATTRIBUTES,
)
_STOCKS = (
    st.none()
    | st.builds(Lot, st.integers(0, len(PLACES) - 1), st.integers(1, 3))
    | st.builds(
        Units,
        st.integers(0, len(PLACES) - 1),
        st.lists(
            st.tuples(st.none() | st.sampled_from(_SERIALS), st.none() | st.sampled_from(_MACS)),
            min_size=1,
            max_size=3,
        ).map(tuple),
    )
)


def parts_for(number: int) -> st.SearchStrategy[NewPart | StoredPart | EarlierRow]:
    earlier = st.builds(EarlierRow, st.integers(2, number - 1)) if number > 2 else st.nothing()
    return _NEW_PARTS | st.builds(StoredPart, st.integers(0, len(PART_IDS) - 1)) | earlier


def doings_for(number: int) -> st.SearchStrategy[Doing]:
    return st.builds(Doing, parts_for(number), _STOCKS)


@st.composite
def doings(draw: st.DrawFn) -> tuple[Doing, ...]:
    """What each row of a sheet does, its rows numbered from 2."""
    count = draw(st.integers(1, 4))
    return tuple(draw(doings_for(number)) for number in range(2, count + 2))


@st.composite
def changed(draw: st.DrawFn, rows: tuple[Doing, ...]) -> tuple[Doing, ...]:
    """The same rows with one of them doing something else, or maybe the same again: its
    part, its stock or both drawn afresh from pools small enough to land near the old."""
    index = draw(st.integers(0, len(rows) - 1))
    old = rows[index]
    part = draw(st.just(old.part) | parts_for(index + 2))
    stock = draw(st.just(old.stock) | _STOCKS)
    return (*rows[:index], Doing(part, stock), *rows[index + 1 :])


@st.composite
def padded(draw: st.DrawFn, text: str | None) -> str | None:
    return None if text is None else draw(_GAPS) + text + draw(_GAPS)


@st.composite
def spelled_macs(draw: st.DrawFn, canonical: str) -> str:
    """A MAC in one of the spellings 06 accepts, in either case."""
    bare = canonical.replace(":", "")
    spellings = [canonical, canonical.replace(":", "-"), bare, f"{bare[:4]}.{bare[4:8]}.{bare[8:]}"]
    spelled = draw(st.sampled_from(spellings))
    return spelled.upper() if draw(st.booleans()) else spelled


@st.composite
def part_outcomes(
    draw: st.DrawFn, part: NewPart | StoredPart | EarlierRow
) -> DefinesPart | NamesPart | SameAsRow:
    if isinstance(part, StoredPart):
        shown = KnownPart(
            PART_IDS[part.part], draw(_TEXT), draw(st.booleans()), draw(st.booleans())
        )
        return NamesPart(shown)
    if isinstance(part, EarlierRow):
        return SameAsRow(part.row, draw(st.none() | st.booleans()), draw(st.none() | st.booleans()))
    typed = draw(st.permutations(part.attributes))
    draft = PartDraft(
        category_path=draw(_OPTIONAL_TEXT),
        name=draw(padded(part.name)),
        manufacturer=draw(padded(part.manufacturer)),
        mpn=draw(padded(part.mpn)),
        package=draw(padded(part.package)),
        attributes={
            key: draw(padded(value)) or "" if isinstance(value, str) else value
            for key, value in typed
        },
    )
    category = None if part.category is None else CATEGORY_IDS[part.category]
    identity = None if part.mpn is None else f"{(part.manufacturer or '').lower()}\n{part.mpn}"
    flags = st.none() | st.booleans()
    return DefinesPart(draft, category, draw(_OPTIONAL_TEXT), identity, draw(flags), draw(flags))


@st.composite
def renamed(draw: st.DrawFn, index: int) -> Location:
    """The location, maybe renamed since: its id is what an import receives into."""
    where = PLACES[index]
    name = LocationName(draw(st.sampled_from([str(where.name), "Renamed"])))
    return Location(where.id, where.workspace_id, where.parent_id, where.code, name, NOW)


@st.composite
def stock_outcomes(
    draw: st.DrawFn, stock: Lot | Units | None
) -> ReceivesLot | ReceivesUnits | None:
    if stock is None:
        return None
    if isinstance(stock, Lot):
        return ReceivesLot(draw(renamed(stock.location)), Quantity(stock.quantity))
    units = tuple(
        UnitLabels(
            None if serial is None else Serial(draw(padded(serial.replace(" ", "\t"))) or ""),
            None if mac is None else Mac(draw(spelled_macs(mac))),
        )
        for serial, mac in stock.labels
    )
    return ReceivesUnits(draw(renamed(stock.location)), units)


_PROBLEMS = st.lists(
    st.builds(
        CellProblem,
        st.none() | st.integers(2, 9),
        st.none() | st.sampled_from(Column),
        st.sampled_from(ProblemCode),
        _TEXT,
    ),
    max_size=2,
).map(tuple)


@st.composite
def plans(draw: st.DrawFn, rows: tuple[Doing, ...]) -> ImportPlan:
    planned = tuple(
        PlannedRow(
            number,
            draw(part_outcomes(doing.part)),
            draw(stock_outcomes(doing.stock)),
            draw(_PROBLEMS),
        )
        for number, doing in enumerate(rows, start=2)
    )
    return ImportPlan(planned, draw(_PROBLEMS))


@given(rows=doings(), data=st.data())
def test_the_digest_follows_what_the_rows_will_do(
    rows: tuple[Doing, ...], data: st.DataObject
) -> None:
    """Property 6: the digest follows what the plan will do (over plans).

    Two plans whose rows do the same, the same parts resolved and the same stock received,
    have the same digest whatever else they carry: problems, the paths and flags shown, the
    names a part or a location has now, spacing around a cell, a MAC's spelling. Two plans
    any of whose rows does something else, a part resolved to another, another location,
    quantity or label, a new part's cell, have different digests.

    **Validates: Requirements 7.4, 8.3**
    """
    other = data.draw(st.just(rows) | changed(rows), label="the rows again, maybe changed")
    plan = data.draw(plans(rows), label="plan")
    again = data.draw(plans(other), label="plan of the other rows")

    assert (plan.digest == again.digest) == (rows == other)


# Then over sheets. The same entries, written with their columns in any order, each header in
# either language, any separator, and each location and MAC spelled any way it reads, plan to
# the same digest. The catalog's half is played by `CATEGORIES`: every row defines a part.

CATEGORIES: Mapping[str, tuple[UUID, bool]] = {
    "Resistors": (uuid7(), False),
    "Boards": (uuid7(), True),
}

_HEADERS: Mapping[str, tuple[str, str]] = {
    Column.CATEGORY: ("category", "Categoria"),
    Column.NAME: ("Name", "nome"),
    Column.MANUFACTURER: ("manufacturer", "Fabricante"),
    Column.MPN: ("part number", "Código do fabricante"),
    Column.PACKAGE: ("package", "encapsulamento"),
    Column.LOCATION: ("location", "Localização"),
    Column.QUANTITY: ("qty", "quantidade"),
    Column.SERIAL: ("serial number", "número de série"),
    Column.MAC: ("MAC address", "endereço MAC"),
    "tolerance": ("tolerance", "Tolerance"),
}
_CASES: tuple[Callable[[str], str], ...] = (str.upper, str.lower, str.title)


@dataclass(frozen=True)
class Entry:
    """One row of a sheet, as the owner means it."""

    category: str
    name: str
    mpn: str | None
    tolerance: str | None
    location: int | None  # an index into PLACES
    quantity: int | None
    serial: str | None
    mac: str | None


@st.composite
def entries(draw: st.DrawFn) -> Entry:
    """Rows that mostly read: a lot of resistors, boards by count, or one labelled board."""
    boards = draw(st.booleans())
    labelled = boards and draw(st.booleans())
    stocked = labelled or draw(st.booleans())
    cap = MAX_UNITS_PER_RECEIPT if boards else MAX_LOT_QUANTITY
    return Entry(
        category="Boards" if boards else "Resistors",
        name=draw(_TEXT),
        mpn=draw(_OPTIONAL_TEXT),
        tolerance=draw(st.none() | st.sampled_from(["1%", "5%"])),
        location=draw(st.integers(0, len(PLACES) - 1)) if stocked else None,
        quantity=draw(st.integers(1, cap)) if stocked and not labelled else None,
        serial=draw(st.sampled_from(_SERIALS)) if labelled else None,
        mac=draw(st.none() | st.sampled_from(_MACS)) if labelled else None,
    )


@st.composite
def spelled_locations(draw: st.DrawFn, index: int) -> str:
    """A location by its short code or its full path, in any case."""
    where = PLACES[index]
    spelled = draw(st.sampled_from([str(where.code), LOCATIONS.path_of(where)]))
    return draw(st.sampled_from(_CASES))(spelled)


@st.composite
def cells_of(draw: st.DrawFn, entry: Entry) -> dict[str, str]:
    location = None if entry.location is None else draw(spelled_locations(entry.location))
    return {
        Column.CATEGORY: draw(padded(entry.category)) or "",
        Column.NAME: draw(padded(entry.name)) or "",
        Column.MPN: draw(padded(entry.mpn)) or "",
        "tolerance": draw(padded(entry.tolerance)) or "",
        Column.LOCATION: location or "",
        Column.QUANTITY: "" if entry.quantity is None else str(entry.quantity),
        Column.SERIAL: entry.serial or "",
        Column.MAC: "" if entry.mac is None else draw(spelled_macs(entry.mac)),
    }


@st.composite
def sheet_texts(draw: st.DrawFn, rows: Sequence[Entry]) -> str:
    """The entries as the text of a sheet, spelled one of the ways that reads the same."""
    columns = draw(st.permutations(list(_HEADERS)))
    headers = {column: draw(st.sampled_from(_HEADERS[column])) for column in columns}
    written = []
    for number, entry in enumerate(rows, start=2):
        cells = draw(cells_of(entry))
        written.append(SheetRow(number, {headers[key]: cell for key, cell in cells.items()}, False))
    sheet = Sheet(tuple(headers[column] for column in columns), tuple(written))
    return write_sheet(sheet, draw(st.sampled_from(SEPARATORS)))


def planned_sheet(text: str) -> ImportPlan:
    """The sheet planned as the import's planner will plan it, each row defining a part in
    the category its cell names."""
    planned = []
    for sheet_row in read_sheet(text).rows:
        draft = PartDraft.of_row(sheet_row)
        category, tracked = CATEGORIES[(draft.category_path or "").strip()]
        identity = None if draft.mpn is None else f"\n{draft.mpn.strip().lower()}"
        part = DefinesPart(draft, category, draft.category_path, identity, tracked, False)
        stock, problems = plan_stock(sheet_row, tracked, False, LOCATIONS)
        planned.append(PlannedRow(sheet_row.number, part, stock, problems))
    return ImportPlan.of(planned)


@given(rows=st.lists(entries(), min_size=1, max_size=4), data=st.data())
def test_the_digest_ignores_how_a_sheet_spells_what_it_does(
    rows: list[Entry], data: st.DataObject
) -> None:
    """Property 6: the digest follows what the plan will do (over sheets).

    The same sheet planned twice gives the same digest, and so does the same sheet with its
    columns in another order, its headers in the other language, another separator, and its
    locations and MACs spelled another way they read.

    **Validates: Requirements 7.4, 8.3**
    """
    text = data.draw(sheet_texts(rows), label="sheet")
    respelled = data.draw(sheet_texts(rows), label="the same sheet, spelled again")

    assert planned_sheet(text).digest == planned_sheet(text).digest
    assert planned_sheet(respelled).digest == planned_sheet(text).digest
