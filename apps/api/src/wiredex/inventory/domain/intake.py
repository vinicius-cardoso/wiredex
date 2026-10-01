"""What a quick-add or each row of a sheet will do, and what stands in its way.

Plain data and pure rules (design, "The plan's vocabulary"). A row's part half is the
catalog's to judge, through the application's port, so here it is only the outcome the port
answered: a new part, a stored one, or the part an earlier row defines. The stock half is
inventory's own, and `plan_stock` holds its rules (requirement 6).

An `ImportPlan` gathers the rows, counts them for the preview's summary and fingerprints what
they will do, so an import can tell that its sheet still does what its preview showed (design
decision 4).
"""

import hashlib
import json
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
from types import MappingProxyType
from uuid import UUID

from wiredex.inventory.domain.errors import (
    AmbiguousLocationError,
    InventoryError,
    LocationNotFoundError,
)
from wiredex.inventory.domain.location import Location, LocationPaths
from wiredex.inventory.domain.sheet import Column, SheetRow
from wiredex.inventory.domain.values import Mac, PartId, Quantity, Serial

# Sized for one transaction on the small host (design decision 10). A row or a quick-add
# receives at most 06's receipt cap of units, or a million of a lot; a sheet receives at most
# 500 units in all, since each unit mints its code with a statement of its own.
MAX_LOT_QUANTITY = 1_000_000
MAX_UNITS_PER_RECEIPT = 100
MAX_SHEET_UNITS = 500


class ProblemCode(StrEnum):
    """What is wrong with a row, a quick-add or a sheet as a whole, as the web translates it
    (design decision 17).

    The first five, and `PART_IN_TRASH`, spell catalog's `DraftProblemKind` exactly: bootstrap
    maps each kind onto the code of its name, so the web translates one code whichever module
    found it.
    """

    UNKNOWN_CATEGORY = "unknown_category"
    AMBIGUOUS_CATEGORY = "ambiguous_category"
    MISSING = "missing"  # no category, no name, or a required attribute left out
    INVALID = "invalid"  # a value its value object or validator refuses
    NOT_AN_ATTRIBUTE = "not_an_attribute"  # a key the row's category doesn't define
    UNKNOWN_LOCATION = "unknown_location"
    AMBIGUOUS_LOCATION = "ambiguous_location"
    LOCATION_NEEDED = "location_needed"  # a quantity, serial or MAC with nowhere to go
    QUANTITY_NEEDED = "quantity_needed"  # a location with nothing to put there
    BAD_QUANTITY = "bad_quantity"  # not a whole number in range
    TOO_MANY_UNITS = "too_many_units"  # more than a receipt's cap of units
    COUNTED_IN_LOTS = "counted_in_lots"  # a serial or MAC on a lot-counted part
    ONE_UNIT_PER_LABEL = "one_unit_per_label"  # a serial or MAC with a quantity other than 1
    BAD_SERIAL = "bad_serial"
    BAD_MAC = "bad_mac"
    SERIAL_TAKEN = "serial_taken"  # by a stored unit of the part, or by an earlier row
    MAC_TAKEN = "mac_taken"  # by any stored unit, or by an earlier row
    EXTRA_CELLS = "extra_cells"  # a non-blank cell past the header's columns
    SHEET_TOO_MANY_UNITS = "sheet_too_many_units"  # the sheet as a whole
    NOT_STOCKED = "not_stocked"  # stock given to a part its category marks not stocked
    # The MPN of a part in the trash (16-soft-delete-and-trash, decision 5): catalog's kind.
    PART_IN_TRASH = "part_in_trash"


@dataclass(frozen=True, slots=True)
class CellProblem:
    """One thing wrong: where it is, a code the web translates, and an English sentence the
    web shows as its detail (requirement 7.6)."""

    row: int | None  # None: the sheet as a whole, or a quick-add
    column: str | None  # a fixed column's value or an attribute key; None: the whole row
    code: ProblemCode
    message: str

    def on_row(self, row: int) -> CellProblem:
        """The same problem, stamped with the row it was found on."""
        return replace(self, row=row)


_NOTHING: Mapping[str, str | bool] = MappingProxyType({})


@dataclass(frozen=True, slots=True)
class PartDraft:
    """The part half of a quick-add or a sheet row, as typed, blank cells dropped."""

    category_id: UUID | None = None  # quick-add picks one
    category_path: str | None = None  # a sheet names one
    name: str | None = None
    manufacturer: str | None = None
    mpn: str | None = None
    package: str | None = None
    # By attribute key. A sheet's cells are text; a quick-add may send a yes-or-no as such.
    attributes: Mapping[str, str | bool] = field(default=_NOTHING)

    @classmethod
    def of_row(cls, row: SheetRow) -> PartDraft:
        """A row's part cells, by column name rather than position, so the columns' order and
        the headers' language don't matter. Every column that isn't fixed is an attribute,
        and a blank cell is an attribute not given (requirement 5.6)."""
        given = {column: cell for column, cell in row.cells.items() if cell.strip()}
        return cls(
            category_path=given.get(Column.CATEGORY),
            name=given.get(Column.NAME),
            manufacturer=given.get(Column.MANUFACTURER),
            mpn=given.get(Column.MPN),
            package=given.get(Column.PACKAGE),
            attributes={key: cell for key, cell in given.items() if key not in _FIXED_COLUMNS},
        )


_FIXED_COLUMNS = frozenset(Column)


@dataclass(frozen=True, slots=True)
class KnownPart:
    """A part the catalog holds, in inventory's words: what a row names, or what intake
    defined."""

    id: PartId
    name: str
    tracked_individually: bool
    not_stocked: bool  # a consumable: intake gives it no stock (09's requirement 2.5)


# What a row does with a part: defines a new one, names a stored one, or uses the part an
# earlier row of the same sheet defines (requirements 5.1-5.3).


@dataclass(frozen=True, slots=True)
class DefinesPart:
    draft: PartDraft
    category_id: UUID | None  # None while the category is a problem
    category_path: str | None
    identity: str | None  # None: no part number, so no later row can name it
    tracked_individually: bool | None
    not_stocked: bool | None  # None while the category is a problem, as tracking is


@dataclass(frozen=True, slots=True)
class NamesPart:
    part: KnownPart


@dataclass(frozen=True, slots=True)
class SameAsRow:
    row: int
    tracked_individually: bool | None
    not_stocked: bool | None


type PartOutcome = DefinesPart | NamesPart | SameAsRow


# What a row puts away: one lot receipt, or units (requirements 6.1-6.3).


@dataclass(frozen=True, slots=True)
class UnitLabels:
    serial: Serial | None
    mac: Mac | None


_UNLABELLED = UnitLabels(None, None)


@dataclass(frozen=True, slots=True)
class ReceivesLot:
    location: Location
    quantity: Quantity


@dataclass(frozen=True, slots=True)
class ReceivesUnits:
    location: Location
    units: tuple[UnitLabels, ...]


type StockOutcome = ReceivesLot | ReceivesUnits


@dataclass(frozen=True, slots=True)
class PlannedRow:
    row: int
    part: PartOutcome
    stock: StockOutcome | None
    problems: tuple[CellProblem, ...]


@dataclass(frozen=True, slots=True)
class ImportSummary:
    """What a preview counts (requirement 7.3)."""

    rows: int
    new_parts: int  # rows defining a part
    existing_parts: int  # distinct stored parts the rows name
    receipts: int  # lot receipts
    pieces: int  # their total quantity
    units: int
    rows_with_problems: int


@dataclass(frozen=True, slots=True)
class ImportPlan:
    rows: tuple[PlannedRow, ...]
    sheet_problems: tuple[CellProblem, ...]

    @classmethod
    def of(cls, rows: Iterable[PlannedRow]) -> ImportPlan:
        """The plan of these rows, with the sheet's own problem when they plan more than
        500 units in all (requirement 6.11)."""
        planned = tuple(rows)
        units = _units_in(planned)
        if units <= MAX_SHEET_UNITS:
            return cls(planned, ())
        problem = CellProblem(
            None,
            None,
            ProblemCode.SHEET_TOO_MANY_UNITS,
            f"a sheet receives at most {MAX_SHEET_UNITS} units, and this one plans {units:,}: "
            f"split it into two",
        )
        return cls(planned, (problem,))

    @property
    def problems(self) -> tuple[CellProblem, ...]:
        """The sheet's problems, then every row's in row order."""
        return (*self.sheet_problems, *(problem for row in self.rows for problem in row.problems))

    @property
    def summary(self) -> ImportSummary:
        lots = [row.stock for row in self.rows if isinstance(row.stock, ReceivesLot)]
        named = {row.part.part.id for row in self.rows if isinstance(row.part, NamesPart)}
        return ImportSummary(
            rows=len(self.rows),
            new_parts=sum(isinstance(row.part, DefinesPart) for row in self.rows),
            existing_parts=len(named),
            receipts=len(lots),
            pieces=sum(int(lot.quantity) for lot in lots),
            units=_units_in(self.rows),
            rows_with_problems=sum(bool(row.problems) for row in self.rows),
        )

    @property
    def digest(self) -> str:
        """The SHA-256, in hex, of what every row will do, in a canonical JSON form (design,
        Data Models): its number, the part it resolves to, and the stock it receives.

        Resolved ids stand for what they resolve, draft cells enter trimmed, and serials and
        MACs as their value objects normalized them, so another column order, header language
        or spelling of the same thing gives the same digest, and any change in what a row will
        do gives another (property 6). Problems stay out: a plan with any is never imported.
        JSON escapes everything past ASCII, so any text a cell can hold encodes, and always
        the same way.
        """
        text = json.dumps([_entry(row) for row in self.rows], separators=(",", ":"))
        return hashlib.sha256(text.encode()).hexdigest()


def _units_in(rows: Iterable[PlannedRow]) -> int:
    return sum(len(row.stock.units) for row in rows if isinstance(row.stock, ReceivesUnits))


# --- A row's stock ---------------------------------------------------------------------------


def plan_stock(
    row: SheetRow, tracked: bool | None, not_stocked: bool | None, locations: LocationPaths
) -> tuple[StockOutcome | None, tuple[CellProblem, ...]]:
    """What a row puts away, and every problem its stock cells have (requirement 6).

    `tracked` is the row's part's resolved flag: units for a unit-tracked part, one lot
    receipt for a lot-counted one. It is None while the part's category is a problem; then
    only what holds for either kind is checked, and nothing is planned. Stock is planned only
    when every stock cell reads, so a row's stock is what an import will receive, or nothing.

    A consumable, whose category resolves `not_stocked`, is never received: any stock given
    to it is one problem on the first stock cell given, whatever the cells hold, and nothing
    is planned (09's requirement 2.5). Without stock it is a row like any other (2.6).
    """
    cells = _StockCells.of(row)
    if cells.empty:
        return None, ()
    if not_stocked:
        return None, (not_stocked_problem(cells.first_given).on_row(row.number),)
    location = _location_in(cells.location, locations)
    count = _count_in(cells, tracked)
    labels = _labels_in(cells, tracked)
    problems = tuple(
        problem.on_row(row.number)
        for problem in (*location.problems, *count.problems, *labels.problems)
    )
    if problems:
        return None, problems
    return _stock(tracked, location.value, count.value, labels.value), ()


def quantity_problem(quantity: int, tracked: bool | None) -> CellProblem | None:
    """The one quantity rule a quick-add and a sheet row answer to (requirements 1.8, 6.8):
    at least 1, and at most 100 units or 1,000,000 of a lot. While the part's kind is unknown
    only what holds for both is checked, and its category's problem is reported anyway.

    The problem is on the quantity, with no row: a sheet's planner stamps it.
    """
    if tracked and quantity > MAX_UNITS_PER_RECEIPT:
        return CellProblem(
            None,
            Column.QUANTITY,
            ProblemCode.TOO_MANY_UNITS,
            f"at most {MAX_UNITS_PER_RECEIPT} units are received at once",
        )
    if 1 <= quantity <= MAX_LOT_QUANTITY:
        return None
    return CellProblem(None, Column.QUANTITY, ProblemCode.BAD_QUANTITY, _IN_RANGE[tracked])


def not_stocked_problem(column: Column) -> CellProblem:
    """Stock given to a consumable, on the cell it was given in: a quick-add's quantity, or a
    row's first stock cell (09's requirement 2.5). The planner stamps a row's number."""
    return CellProblem(
        None,
        column,
        ProblemCode.NOT_STOCKED,
        "this part's category isn't stocked, so none of it is received: leave its stock blank",
    )


_IN_RANGE: Mapping[bool | None, str] = {
    True: f"a quantity of units is a whole number from 1 to {MAX_UNITS_PER_RECEIPT}",
    False: f"a lot's quantity is a whole number from 1 to {MAX_LOT_QUANTITY:,}",
    None: f"a quantity is a whole number from 1 to {MAX_LOT_QUANTITY:,}",
}


@dataclass(frozen=True, slots=True)
class _StockCells:
    """A row's four stock cells, None where blank."""

    location: str | None
    quantity: str | None
    serial: str | None
    mac: str | None

    @classmethod
    def of(cls, row: SheetRow) -> _StockCells:
        cells = row.cells
        return cls(
            _given(cells.get(Column.LOCATION)),
            _given(cells.get(Column.QUANTITY)),
            _given(cells.get(Column.SERIAL)),
            _given(cells.get(Column.MAC)),
        )

    @property
    def labelled(self) -> bool:
        return self.serial is not None or self.mac is not None

    @property
    def empty(self) -> bool:
        """Nothing to put away: the row plans no stock (requirement 6.7)."""
        return self.location is None and self.quantity is None and not self.labelled

    @property
    def first_given(self) -> Column:
        """The first stock cell given, in the order quantity, location, serial, MAC: where a
        refusal of the whole stock is reported. Only asked of cells that aren't empty."""
        given = (
            (Column.QUANTITY, self.quantity),
            (Column.LOCATION, self.location),
            (Column.SERIAL, self.serial),
        )
        return next((column for column, cell in given if cell is not None), Column.MAC)


@dataclass(frozen=True, slots=True)
class _Read[T]:
    """One stock cell read: its value, or the problems standing in its way. Neither means
    the cell needed no value."""

    value: T | None = None
    problems: tuple[CellProblem, ...] = ()


def _location_in(text: str | None, locations: LocationPaths) -> _Read[Location]:
    """The location the cell names. Another stock cell was given, so a blank one is missing
    (requirement 6.6)."""
    if text is None:
        return _problem(
            Column.LOCATION,
            ProblemCode.LOCATION_NEEDED,
            "stock needs a location to go into: its short code or its path",
        )
    try:
        return _Read(locations.find(text))
    except LocationNotFoundError as error:
        return _problem(Column.LOCATION, ProblemCode.UNKNOWN_LOCATION, str(error))
    except AmbiguousLocationError as error:
        return _problem(Column.LOCATION, ProblemCode.AMBIGUOUS_LOCATION, str(error))


def _count_in(cells: _StockCells, tracked: bool | None) -> _Read[int]:
    """How many the row puts away. A serial or a MAC labels one unit, so beside one the
    quantity is blank or 1 (requirement 6.3); on a part counted in lots the label itself is
    the problem, which `_labels_in` reports."""
    if cells.labelled and tracked is not False:
        return _one_unit(cells.quantity)
    if cells.quantity is not None:
        return _quantity_in(cells.quantity, tracked)
    if cells.labelled:
        return _Read()
    return _problem(
        Column.QUANTITY, ProblemCode.QUANTITY_NEEDED, "a location needs a quantity to put there"
    )


def _one_unit(text: str | None) -> _Read[int]:
    if text is None or _whole_number(text) == 1:
        return _Read(1)
    return _problem(
        Column.QUANTITY,
        ProblemCode.ONE_UNIT_PER_LABEL,
        "a serial or a MAC labels one unit, so its quantity is blank or 1",
    )


def _quantity_in(text: str, tracked: bool | None) -> _Read[int]:
    quantity = _whole_number(text)
    if quantity is None:
        return _problem(
            Column.QUANTITY,
            ProblemCode.BAD_QUANTITY,
            f"a quantity is written in digits only, like 1000, not {text.strip()!r}",
        )
    problem = quantity_problem(quantity, tracked)
    return _Read(quantity) if problem is None else _Read(problems=(problem,))


def _labels_in(cells: _StockCells, tracked: bool | None) -> _Read[UnitLabels]:
    """The serial and MAC of the one unit a row labels, each read by its value object, so a
    MAC is kept in its canonical form (requirement 6.10). On a part counted in lots they are
    a problem whatever they hold (requirement 6.4)."""
    if not cells.labelled:
        return _Read()
    serial = _label(cells.serial, Serial, Column.SERIAL, ProblemCode.BAD_SERIAL)
    mac = _label(cells.mac, Mac, Column.MAC, ProblemCode.BAD_MAC)
    problems = (*serial.problems, *mac.problems)
    if tracked is False:
        problems = (_counted_in_lots(cells), *problems)
    if problems:
        return _Read(problems=problems)
    return _Read(UnitLabels(serial.value, mac.value))


def _label[T](
    text: str | None, read: Callable[[str], T], column: Column, code: ProblemCode
) -> _Read[T]:
    """A label through its value object, whose sentence says what it refused."""
    if text is None:
        return _Read()
    try:
        return _Read(read(text))
    except InventoryError as error:
        return _problem(column, code, str(error))


def _counted_in_lots(cells: _StockCells) -> CellProblem:
    column = Column.SERIAL if cells.serial is not None else Column.MAC
    return CellProblem(
        None,
        column,
        ProblemCode.COUNTED_IN_LOTS,
        "this part is counted in lots, so it takes a quantity, not a serial or a MAC",
    )


def _stock(
    tracked: bool | None, location: Location | None, count: int | None, labels: UnitLabels | None
) -> StockOutcome | None:
    """The receipt the cells make, nothing while the part's kind is unknown. A location or a
    count left without a value always came with a problem, so neither is None past here."""
    if tracked is None or location is None or count is None:
        return None
    if not tracked:
        return ReceivesLot(location, Quantity(count))
    units = (labels,) if labels is not None else (_UNLABELLED,) * count
    return ReceivesUnits(location, units)


def _problem[T](column: Column, code: ProblemCode, message: str) -> _Read[T]:
    return _Read(problems=(CellProblem(None, column, code, message),))


def _given(text: str | None) -> str | None:
    """The cell, or None when it is blank: a blank cell is nothing given."""
    return None if text is None or not text.strip() else text


# Digits only: no sign, no thousands separator, no unit. `int()` would also take `+3`,
# `1_000` and other scripts' digits, which a spreadsheet's quantity never means.
_DIGITS = re.compile(r"[0-9]+")
# More significant digits than the largest cap has is past every cap, and `int()` refuses
# text past 4,300 digits, so a longer number is judged by its length alone.
_MAX_DIGITS = len(str(MAX_LOT_QUANTITY))


def _whole_number(text: str) -> int | None:
    """The cell as a whole number, or None when it isn't one. A number too long to be under
    any cap reads as the first one past them all, since no refusal quotes it."""
    digits = text.strip()
    if not _DIGITS.fullmatch(digits):
        return None
    significant = digits.lstrip("0") or "0"
    return int(significant) if len(significant) <= _MAX_DIGITS else MAX_LOT_QUANTITY + 1


# --- What a sheet has planned so far ---------------------------------------------------------


class SheetBook:
    """What a sheet has planned so far, so that a later row's repeat names the earlier row
    (requirements 5.2 and 6.9).

    It remembers the first row of each part identity, of each serial per part, and of each
    MAC. A part is known by the first row that resolves to it: rows naming one stored part
    share its identity, and a row without a part number is a part of its own.
    """

    __slots__ = ("_macs", "_parts", "_serials")

    def __init__(self) -> None:
        self._parts: dict[str, int] = {}
        self._serials: dict[tuple[int, str], int] = {}
        self._macs: dict[str, int] = {}

    def part_row(self, identity: str | None, row: int) -> int:
        """The first row that gives this identity: an earlier row, or `row` itself, which is
        remembered as the first. A row without an identity is always its own."""
        if identity is None:
            return row
        return self._parts.setdefault(identity, row)

    def label_problems(
        self, part_row: int, labels: UnitLabels, row: int
    ) -> tuple[CellProblem, ...]:
        """A problem for each label an earlier row already gives, naming that row: a serial
        on the same part, compared case-folded as the index compares it, or a MAC on any
        part. The labels this row is the first to give are remembered."""
        problems: list[CellProblem] = []
        if labels.serial is not None:
            key = (part_row, labels.serial.fold())
            earlier = self._serials.setdefault(key, row)
            if earlier != row:
                message = f"row {earlier} already gives this part the serial {labels.serial}"
                problems.append(CellProblem(row, Column.SERIAL, ProblemCode.SERIAL_TAKEN, message))
        if labels.mac is not None:
            earlier = self._macs.setdefault(labels.mac.value, row)
            if earlier != row:
                message = f"row {earlier} already has the MAC {labels.mac}"
                problems.append(CellProblem(row, Column.MAC, ProblemCode.MAC_TAKEN, message))
        return tuple(problems)


# --- The digest's canonical form -------------------------------------------------------------

type _Json = str | int | bool | list[_Json] | None


def _entry(row: PlannedRow) -> _Json:
    return [row.row, _part_entry(row.part), _stock_entry(row.stock)]


def _part_entry(part: PartOutcome) -> _Json:
    if isinstance(part, NamesPart):
        return ["names", str(part.part.id)]
    if isinstance(part, SameAsRow):
        return ["same_as", part.row]
    draft = part.draft
    cells = (draft.name, draft.manufacturer, draft.mpn, draft.package)
    attributes: list[_Json] = [
        [key, _trimmed(draft.attributes[key])] for key in sorted(draft.attributes)
    ]
    return [
        "defines",
        _text(part.category_id),
        part.identity,
        *(_trimmed(cell) for cell in cells),
        attributes,
    ]


def _stock_entry(stock: StockOutcome | None) -> _Json:
    if stock is None:
        return None
    if isinstance(stock, ReceivesLot):
        return ["lot", str(stock.location.id), int(stock.quantity)]
    labels: list[_Json] = [[_text(unit.serial), _text(unit.mac)] for unit in stock.units]
    return ["units", str(stock.location.id), labels]


def _trimmed(value: str | bool | None) -> str | bool | None:
    return value.strip() if isinstance(value, str) else value


def _text(value: UUID | Serial | Mac | None) -> str | None:
    return None if value is None else str(value)
