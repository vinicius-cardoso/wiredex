"""What inventory takes and gives over HTTP, in primitives only.

No domain object reaches a field: the `from_*` classmethods do the converting, as catalog's
do. Movement responses carry the resulting balance so the web updates without a refetch — a
receive or adjust answers one balance, a move answers both lots' (design's HTTP API).
"""

from collections.abc import Mapping
from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, Field

from wiredex.inventory.application.imports import ImportedPart, ImportResult
from wiredex.inventory.application.intake import QuickAdded
from wiredex.inventory.application.ports import (
    LocationNode,
    LotBalance,
    PartStockView,
)
from wiredex.inventory.application.units import UnitsReceived
from wiredex.inventory.domain.errors import (
    IntakeRefusedError,
    PartAlreadyDefinedError,
    SheetUnreadableError,
)
from wiredex.inventory.domain.intake import (
    MAX_UNITS_PER_RECEIPT,
    CellProblem,
    DefinesPart,
    ImportPlan,
    ImportSummary,
    NamesPart,
    PartOutcome,
    PlannedRow,
    ReceivesLot,
    StockOutcome,
    UnitLabels,
)
from wiredex.inventory.domain.location import Location
from wiredex.inventory.domain.lot import StockBalance
from wiredex.inventory.domain.sheet import MAX_SHEET_CHARACTERS
from wiredex.inventory.domain.unit import Unit

# The reasons an adjust may carry, spelled out for the wire so the generated client gets a
# union it can switch on. A test keeps this in step with the `MovementReason` enum.
type MovementReasonName = Literal["recount", "damaged", "lost", "found", "correction"]

# A retire's reason is one of the two a lost or broken board gets; `damaged` is the default a
# body may leave out. Narrower than `MovementReasonName` on purpose: the other reasons belong
# to an adjust, not to retiring a unit (design's HTTP API).
type RetireReasonName = Literal["damaged", "lost"]

# A unit's status on the wire, the four v0.5.0 values (design's decision 5). A test keeps
# this in step with the `UnitStatus` enum.
type UnitStatusName = Literal["in_stock", "reserved", "in_use", "retired"]

# What is wrong with a quick-add, a sheet row or a sheet, spelled out so the web has a
# sentence for each in both languages (design decision 17). A test keeps this in step with
# the `ProblemCode` enum, and another with `SheetRefusalName` for `SheetRefusal`.
type ProblemCodeName = Literal[
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
]
# Why a sheet can't be read at all: the one refusal a preview answers as a 422.
type SheetRefusalName = Literal[
    "not_utf8", "empty", "unknown_column", "duplicate_column", "too_many_columns", "too_many_rows"
]
# What a planned row does with a part, and what it puts away.
type PartOutcomeName = Literal["new", "existing", "same_as_row"]
type StockOutcomeName = Literal["lot", "units"]


class CreateLocationRequest(BaseModel):
    name: str
    # No parent makes it a root location (requirements 1.1, 1.2).
    parent_id: UUID | None = None


class UpdateLocationRequest(BaseModel):
    """A rename, a move, or both. What the body left out is left alone.

    `parent_id: null` is a move to the root, a different thing from not sending it, so the
    handler asks `moves()` rather than reading the value, as catalog's category patch does.
    """

    name: str | None = None
    parent_id: UUID | None = None

    def moves(self) -> bool:
        return "parent_id" in self.model_fields_set


class ReceiveRequest(BaseModel):
    """Receiving a positive quantity of a part into a location (requirement 4.1)."""

    part_id: UUID
    location_id: UUID
    quantity: int = Field(ge=1)
    note: str | None = None


class AdjustRequest(BaseModel):
    """Recounting a lot to an absolute counted quantity, with a reason (4.3, 4.4).

    `counted` is the absolute number the owner counted, not a delta: the use case works out
    the signed change and stores that.
    """

    part_id: UUID
    location_id: UUID
    counted: int = Field(ge=0)
    reason: MovementReasonName
    note: str | None = None


class MoveRequest(BaseModel):
    """Moving a positive quantity of a part from one location to another (requirement 4.5)."""

    part_id: UUID
    from_location_id: UUID
    to_location_id: UUID
    quantity: int = Field(ge=1)
    note: str | None = None


class LocationResponse(BaseModel):
    """A location on the wire, its short code shown so a bin reads as `WX-L-0007` (2.1)."""

    id: UUID
    parent_id: UUID | None
    code: str
    name: str
    created_at: datetime

    @classmethod
    def from_location(cls, location: Location) -> Self:
        return cls(
            id=location.id,
            parent_id=location.parent_id,
            code=str(location.code),
            name=location.name.value,
            created_at=location.created_at,
        )


class LocationNodeResponse(LocationResponse):
    """A location as the tree shows it, with the counts requirement 1.12 asks for."""

    child_count: int
    lot_count: int

    @classmethod
    def from_node(cls, node: LocationNode) -> Self:
        base = LocationResponse.from_location(node.location)
        return cls(**base.model_dump(), child_count=node.child_count, lot_count=node.lot_count)


class BalanceResponse(BaseModel):
    """The resulting balance a movement answers with, so the web updates in place.

    `available` is `on_hand - reserved`; in v0.4.0 `reserved` is always zero, so it equals
    `on_hand`, but the field is here from day one (design's HTTP API, requirement 3.4).
    """

    lot_id: UUID
    on_hand: int
    reserved: int
    available: int

    @classmethod
    def from_balance(cls, balance: StockBalance) -> Self:
        return cls(
            lot_id=balance.lot_id,
            on_hand=int(balance.on_hand),
            reserved=int(balance.reserved),
            available=int(balance.available),
        )


class MoveResponse(BaseModel):
    """Both lots' balances after a move: what left the source, and what the destination now
    holds (design's HTTP API)."""

    source: BalanceResponse
    destination: BalanceResponse

    @classmethod
    def from_balances(cls, source: StockBalance, destination: StockBalance) -> Self:
        return cls(
            source=BalanceResponse.from_balance(source),
            destination=BalanceResponse.from_balance(destination),
        )


class PartTotalResponse(BaseModel):
    """One part's total on_hand, for the batch the parts list asks for (requirements 7.1, 7.2)."""

    part_id: UUID
    on_hand: int


class LotBalanceResponse(BaseModel):
    """One row of a part's per-location breakdown: where, and how much sits there (7.3)."""

    location: LocationResponse
    on_hand: int

    @classmethod
    def from_lot_balance(cls, row: LotBalance) -> Self:
        return cls(
            location=LocationResponse.from_location(row.location),
            on_hand=int(row.on_hand),
        )


class PartStockResponse(BaseModel):
    """A part's total on_hand and its breakdown by location (requirements 7.3, 7.4).

    A part never received reports a total of zero and an empty breakdown, not a 404.
    """

    total: int
    breakdown: list[LotBalanceResponse]

    @classmethod
    def from_view(cls, view: PartStockView) -> Self:
        return cls(
            total=view.total,
            breakdown=[LotBalanceResponse.from_lot_balance(row) for row in view.breakdown],
        )


# --- Units --------------------------------------------------------------------------------


class NewUnitBody(BaseModel):
    """One unit in a receipt: an optional serial and MAC, either or both may be blank (5.5).

    The MAC is taken in any accepted spelling and canonicalized by the `Mac` value object;
    the router hands it over as typed so a malformed one is a 422 with the field named.
    """

    serial: str | None = None
    mac: str | None = None


class ReceiveUnitsRequest(BaseModel):
    """Receiving units of a unit-tracked part into a location (requirement 1.1).

    The `units` list's length is the quantity: one entry per unit, so N units are one
    `RECEIVE` of N on the (part, location) lot. At least one unit, since a receipt of nothing
    is nothing to do, and at most the web form's hundred: each unit mints its code with its
    own statement, so an unbounded list would hold the transaction open for as long as it
    was long.
    """

    part_id: UUID
    location_id: UUID
    units: list[NewUnitBody] = Field(min_length=1, max_length=MAX_UNITS_PER_RECEIPT)


class RelabelUnitRequest(BaseModel):
    """A unit's serial and MAC, both optional and both replaced by what the body carries.

    A field left `null` clears that label; the use case refuses a duplicate and commits
    nothing when neither changed (requirement 5.6).
    """

    serial: str | None = None
    mac: str | None = None


class MoveUnitRequest(BaseModel):
    """Moving one unit to a destination location (requirement 4.1)."""

    to_location_id: UUID


class RetireUnitRequest(BaseModel):
    """Retiring a unit, with the reason it left stock; `damaged` when the body omits it (3.1)."""

    reason: RetireReasonName = "damaged"


class UnitResponse(BaseModel):
    """A unit on the wire: its identity, its status, and where it sits (requirements 6.1, 8.3).

    The location is the unit's lot's location, resolved by the API; it is present for every
    unit (a unit always points at a lot in some location), but typed optional so a response
    never fails to serialize if a lot were ever missing. The MAC and serial are the canonical
    stored forms.
    """

    id: UUID
    part_id: UUID
    lot_id: UUID
    code: str
    serial: str | None
    mac: str | None
    status: UnitStatusName
    location: LocationResponse | None
    created_at: datetime

    @classmethod
    def of(cls, unit: Unit, location: Location | None) -> Self:
        return cls(
            id=unit.id,
            part_id=unit.part_id,
            lot_id=unit.lot_id,
            code=str(unit.code),
            serial=None if unit.serial is None else str(unit.serial),
            mac=None if unit.mac is None else str(unit.mac),
            status=unit.status.value,
            location=None if location is None else LocationResponse.from_location(location),
            created_at=unit.created_at,
        )


class ReceiveUnitsResponse(BaseModel):
    """A receipt's result: the units created (each with its minted code) and the lot's new
    balance, so the web shows the codes and updates the balance without a refetch (design's
    HTTP API)."""

    units: list[UnitResponse]
    balance: BalanceResponse

    @classmethod
    def of(cls, received: UnitsReceived, location: Location | None) -> Self:
        return cls(
            units=[UnitResponse.of(unit, location) for unit in received.units],
            balance=BalanceResponse.from_balance(received.balance),
        )


# --- Quick-add and import ---------------------------------------------------------------


class QuickPartBody(BaseModel):
    """The part half of a quick-add, as the dialog typed it (requirement 1.1).

    Every field may be left out, the category and the name too: the catalog is the one
    authority on what a new part needs, so a blank one comes back as a `missing` problem on
    its field, beside every other problem, rather than as a schema refusal on its own (1.5).
    Attribute values are what the part form sends, text as typed (`4k7`) or a switch's
    boolean; null or blank text is nothing given.
    """

    category_id: UUID | None = None
    name: str | None = None
    manufacturer: str | None = None
    mpn: str | None = None
    package: str | None = None
    attributes: dict[str, str | bool | None] = Field(default_factory=dict)


class QuickStockBody(BaseModel):
    """Where a quick-add's first stock goes and how much (design decision 11).

    Both halves or no stock at all: a body giving one without the other is refused by the
    schema, naming the one it lacks (requirement 1.7). The quantity's range is left to the use
    case, since it depends on how the part is counted, and is reported with every other
    problem (1.8).
    """

    location_id: UUID
    quantity: int


class QuickAddRequest(BaseModel):
    """A part, optionally its first stock, and for a duplicate the part whose pinout it
    copies (requirements 1 and 3.2)."""

    part: QuickPartBody
    stock: QuickStockBody | None = None
    pinout_from: UUID | None = None


class QuickAddResponse(BaseModel):
    """What a quick-add added: the part, and the lot's balance or the units it received, each
    with its minted code and location (requirements 1.2, 1.3). `balance` is null for units
    and for a part added without stock."""

    part_id: UUID
    name: str
    balance: BalanceResponse | None
    units: list[UnitResponse]

    @classmethod
    def of(cls, added: QuickAdded, units: list[UnitResponse]) -> Self:
        balance = added.balance
        return cls(
            part_id=added.part.id,
            name=added.part.name,
            balance=None if balance is None else BalanceResponse.from_balance(balance),
            units=units,
        )


class CellProblemResponse(BaseModel):
    """One thing wrong, where it is, and a code the web translates (requirement 7.6).

    `row` is null for a quick-add and for the sheet as a whole; `column` is a fixed column's
    name or an attribute key, and null for a whole row. The message is English and safe to
    show as the detail of a refused value.
    """

    row: int | None
    column: str | None
    code: ProblemCodeName
    message: str

    @classmethod
    def from_problem(cls, problem: CellProblem) -> Self:
        return cls(
            row=problem.row,
            column=None if problem.column is None else str(problem.column),
            code=_problem_code_name(problem),
            message=problem.message,
        )


class ImportSheetRequest(BaseModel):
    """A sheet's text, for a preview. The characters are capped here, before it is read
    (design's Limits); the entries and columns are the reader's to count."""

    csv: str = Field(max_length=MAX_SHEET_CHARACTERS)


class ImportRequest(ImportSheetRequest):
    """The previewed sheet sent back with the digest its preview answered, so the import
    refuses a sheet whose outcome changed since (requirement 8.3)."""

    digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class ImportSummaryResponse(BaseModel):
    """What a sheet does, counted (requirement 7.3)."""

    rows: int
    new_parts: int
    existing_parts: int
    receipts: int
    pieces: int
    units: int
    rows_with_problems: int

    @classmethod
    def from_summary(cls, summary: ImportSummary) -> Self:
        return cls(
            rows=summary.rows,
            new_parts=summary.new_parts,
            existing_parts=summary.existing_parts,
            receipts=summary.receipts,
            pieces=summary.pieces,
            units=summary.units,
            rows_with_problems=summary.rows_with_problems,
        )


class PartOutcomeResponse(BaseModel):
    """What a row does with a part (requirement 7.2).

    `new` carries the name and category path the row gives, `existing` the stored part's id
    and name, and `same_as_row` the earlier row defining the part, with that row's name and
    category. What a kind doesn't have is null.
    """

    kind: PartOutcomeName
    part_id: UUID | None
    name: str | None
    category: str | None
    same_as_row: int | None

    @classmethod
    def from_outcome(cls, outcome: PartOutcome, defined: Mapping[int, DefinesPart]) -> Self:
        if isinstance(outcome, NamesPart):
            part = outcome.part
            return cls(
                kind="existing", part_id=part.id, name=part.name, category=None, same_as_row=None
            )
        if isinstance(outcome, DefinesPart):
            return cls(
                kind="new",
                part_id=None,
                name=_shown_name(outcome),
                category=outcome.category_path,
                same_as_row=None,
            )
        earlier = defined.get(outcome.row)
        return cls(
            kind="same_as_row",
            part_id=None,
            name=None if earlier is None else _shown_name(earlier),
            category=None if earlier is None else earlier.category_path,
            same_as_row=outcome.row,
        )


class PlannedUnitResponse(BaseModel):
    """One unit a row will receive: its serial and MAC in their canonical forms, both null
    for an unlabelled unit."""

    serial: str | None
    mac: str | None

    @classmethod
    def from_labels(cls, labels: UnitLabels) -> Self:
        return cls(
            serial=None if labels.serial is None else str(labels.serial),
            mac=None if labels.mac is None else str(labels.mac),
        )


class StockOutcomeResponse(BaseModel):
    """What a row puts away, and where (requirement 7.2): a lot's quantity, or units, whose
    count is the quantity and each of which is listed with its labels."""

    kind: StockOutcomeName
    location: LocationResponse
    quantity: int
    units: list[PlannedUnitResponse]

    @classmethod
    def from_outcome(cls, outcome: StockOutcome) -> Self:
        location = LocationResponse.from_location(outcome.location)
        if isinstance(outcome, ReceivesLot):
            return cls(kind="lot", location=location, quantity=int(outcome.quantity), units=[])
        return cls(
            kind="units",
            location=location,
            quantity=len(outcome.units),
            units=[PlannedUnitResponse.from_labels(unit) for unit in outcome.units],
        )


class ImportRowResponse(BaseModel):
    """One planned row: its number as the spreadsheet shows it, the part, the stock (null
    for none) and every problem found in it (requirement 7.2)."""

    row: int
    part: PartOutcomeResponse
    stock: StockOutcomeResponse | None
    problems: list[CellProblemResponse]

    @classmethod
    def from_row(cls, row: PlannedRow, defined: Mapping[int, DefinesPart]) -> Self:
        return cls(
            row=row.row,
            part=PartOutcomeResponse.from_outcome(row.part, defined),
            stock=None if row.stock is None else StockOutcomeResponse.from_outcome(row.stock),
            problems=[CellProblemResponse.from_problem(problem) for problem in row.problems],
        )


class ImportPreviewResponse(BaseModel):
    """A preview's plan, problems included, since finding them is what a preview is for
    (requirements 7.2-7.5). `problems` are the sheet's own; each row carries its own. The
    import sends `digest` back."""

    digest: str
    summary: ImportSummaryResponse
    problems: list[CellProblemResponse]
    rows: list[ImportRowResponse]

    @classmethod
    def from_plan(cls, plan: ImportPlan) -> Self:
        defined = {row.row: row.part for row in plan.rows if isinstance(row.part, DefinesPart)}
        return cls(
            digest=plan.digest,
            summary=ImportSummaryResponse.from_summary(plan.summary),
            problems=[CellProblemResponse.from_problem(p) for p in plan.sheet_problems],
            rows=[ImportRowResponse.from_row(row, defined) for row in plan.rows],
        )


class ImportedPartResponse(BaseModel):
    """A part an import defined, and the row that defined it (requirement 8.5)."""

    row: int
    part_id: UUID
    name: str

    @classmethod
    def from_imported(cls, imported: ImportedPart) -> Self:
        return cls(row=imported.row, part_id=imported.part.id, name=imported.part.name)


class ImportResultResponse(BaseModel):
    """What an import did (requirement 8.5): the summary, the parts it defined with their
    rows, and the units it received, each with its minted code and location."""

    summary: ImportSummaryResponse
    parts: list[ImportedPartResponse]
    units: list[UnitResponse]

    @classmethod
    def of(cls, result: ImportResult, units: list[UnitResponse]) -> Self:
        return cls(
            summary=ImportSummaryResponse.from_summary(result.summary),
            parts=[ImportedPartResponse.from_imported(part) for part in result.parts],
            units=units,
        )


# The `detail` of the three structured refusals (design's Error Handling). Like catalog's
# `PinoutRefusalResponse`, they ride an HTTPException rather than a route's response model,
# so the web parses them from the error body.


class IntakeRefusalResponse(BaseModel):
    """A quick-add, or an import whose plan has problems, refused with every problem at once
    (requirements 1.5, 8.2)."""

    message: str
    problems: list[CellProblemResponse]

    @classmethod
    def from_error(cls, error: IntakeRefusedError) -> Self:
        return cls(
            message=str(error),
            problems=[CellProblemResponse.from_problem(p) for p in error.problems],
        )


class SheetRefusalResponse(BaseModel):
    """A sheet that can't be read at all (requirements 4.4-4.6): why, as a code the web
    translates, and the column it is about, when it is about one."""

    message: str
    code: SheetRefusalName
    column: str | None

    @classmethod
    def from_error(cls, error: SheetUnreadableError) -> Self:
        code: SheetRefusalName = error.code.value
        return cls(message=str(error), code=code, column=error.column)


class PartTakenResponse(BaseModel):
    """A quick-add whose manufacturer and part number a stored part holds (requirement 1.6):
    that part, so the owner can open it instead."""

    message: str
    part_id: UUID
    name: str

    @classmethod
    def from_error(cls, error: PartAlreadyDefinedError) -> Self:
        return cls(message=str(error), part_id=error.part.id, name=error.part.name)


def _problem_code_name(problem: CellProblem) -> ProblemCodeName:
    # As catalog's `_problem_name`: a new code stops type-checking here until the wire
    # contract above lists it too.
    name: ProblemCodeName = problem.code.value
    return name


def _shown_name(part: DefinesPart) -> str | None:
    """A new part's name as the preview shows it: spacing collapsed, as the catalog stores
    it; null while the row leaves it blank."""
    name = part.draft.name
    return None if name is None else " ".join(name.split()) or None
